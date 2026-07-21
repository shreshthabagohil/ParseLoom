# MILESTONE_LOG.md

Append-only. Never delete, rewrite, or summarize away a previous entry.
Every future session must read this file in full, alongside
`REBUILD_PLAN.md` and the five files listed in `REBUILD_PROMPT.md` Section
0, before starting or continuing any milestone.

An entry is written only once every test required to close that milestone
(per `REBUILD_PLAN.md`) actually passes — not before, not as a draft. If a
milestone took multiple attempts, the entry documents the whole arc: what
broke, what the real symptom was, root cause, and the exact fix — not just
the final clean state.

No milestone has closed yet. The first entry will be Milestone 0.

---

## Milestone 0: Eliminate main.py/app.py parse_one_resume duplication — 2026-07-20

### Goal
One canonical parsing pipeline function exists and is imported by both
`main.py` and `app.py`, with zero behavior change from today.

### What was done
Created `src/pipeline.py` with a single `parse_one_resume(path: str) ->
ParsedResume` function — the exact logic previously duplicated
byte-for-byte (aside from a docstring) between `main.py` and `app.py`.
Updated both files to `from src.pipeline import parse_one_resume` and
deleted both local definitions, along with the now-unused direct imports
each file had pulled in only to support its own copy (`LLMError`,
`extract`, `extract_contact_and_redact`, `extract_structured_fields`,
`normalize_grade`, `find_and_normalize_from_raw_text`, `ParsedResume` in
`app.py`'s case — `app.py` still needs `ParsedResume`-adjacent behavior
but not the direct import since it no longer constructs one itself).

### Problems faced
The repo's `.venv` was created on the user's Mac (`pyvenv.cfg` points at
`/Library/Frameworks/Python.framework/Versions/3.11/...`) and is a broken
symlink inside this Linux sandbox — `.venv/bin/python3` doesn't resolve.
Worked around by installing `requirements.txt` directly via
`pip3 install --break-system-packages` against the sandbox's system
Python 3.10 instead of trying to repair or reuse `.venv`. This is a
sandbox-only workaround; the user's own Mac `.venv` is untouched and
should still work fine there. Noted here so a future session doesn't
waste time trying to activate `.venv` inside this sandbox again.

### Test failures and how they were resolved
None. This was a pure move with no logic changes, so no test failures
occurred. `pytest tests/` was green on the first run after the refactor
(29/29, unchanged from before).

### Final test results
- Unit: `pytest tests/` — 29/29 passed, unmodified from pre-refactor.
- Code health: `grep -rn "^def parse_one_resume"` across the whole repo
  (excluding `__pycache__`/`.venv`) returns exactly one match, in
  `src/pipeline.py`. AST-parsed `main.py` and `app.py` confirm neither
  file has a local `FunctionDef` named `parse_one_resume` anymore.
- Integration: both `main.py` and `app.py` import cleanly with no
  circular-import or syntax errors; `main.parse_one_resume is
  app.parse_one_resume` is `True`, confirming both modules genuinely
  share the same function object, not just equivalent code.
- Integration (behavioral): ran the shared `parse_one_resume` against the
  three fixture PDFs that don't require an LLM call
  (`mock_corrupted_file.pdf`, `mock_empty_file.pdf`,
  `mock_sparse_resume.pdf`) — all three produced `parse_status="Failed"`
  with the same notes/reasoning documented in `PROJECT_CONTEXT.md`
  Section 11.5 (corrupted/empty caught without crashing, sparse resume
  correctly fails after OCR still yields too little text). LLM-requiring
  fixtures were not run in this milestone since no LLM-path logic changed
  at all — real-LLM verification is deferred to Milestone 1, which
  changes LLM-path behavior and needs real calls anyway.

### Notes for future milestones
- `src/pipeline.py` is now the one place to change resume-parsing logic.
  Milestone 1's new `llm_call_failed`/`llm_failure_reason` fields and the
  timing-instrumentation wrapper both belong here.
- `app.py` no longer imports `ParsedResume` directly — if a future
  milestone needs to construct a `ParsedResume` inside `app.py` again
  (unlikely, but noting it), re-add that import rather than assuming it's
  still there.

### Recurring-risk issues
- **`.venv` is host-specific and will not work inside this sandbox
  environment.** If a future session hits `ModuleNotFoundError` or a
  broken-symlink error activating `.venv` here, don't debug the venv —
  just `pip3 install --break-system-packages -r requirements.txt` against
  the sandbox's own Python. This is a sandbox quirk, not a project bug,
  and doesn't affect the user's own Mac setup.

---

## Milestone 1: Distinct LLM-failure state + timing instrumentation — 2026-07-20

### Goal
A resume whose LLM call genuinely failed (rate limit, bad key, timeout,
malformed JSON) is structurally and visually distinguishable, at every
layer, from a resume that parsed thinly on its own merits.

### What was done
- `src/models.py`: added `llm_call_failed: bool` and `llm_failure_reason:
  str | None` to `ParsedResume`, and `llm_call_failed: bool` to
  `ScoreResult`. `parse_status` keeps its existing three values for CLI
  backward compatibility; `llm_call_failed` is the new, independently
  checked signal.
- `src/pipeline.py::parse_one_resume`: on `LLMError`, now sets both new
  fields (reason string is already scrubbed of secrets by
  `ai_client._scrub_secrets` before `LLMError` is raised, confirmed, not
  assumed — see Test failures section). Added
  `summarize_llm_failures(resumes)` as the one place the "N/M resumes
  failed AI extraction" batch-warning threshold (50%) and message are
  defined, imported by both `main.py` (printed to stderr) and `app.py`
  (returned in the JSON response) and `report.py` (written into
  `parse_quality_report.md`) — one definition, three consumers, not three
  copies of the same threshold logic.
- `src/timing.py`: new, standalone module (`time_stage` context manager +
  `get_recorded_timings()`), logs `STAGE_TIMING resume_file=... stage=...
  duration_ms=... status=...` at INFO level. Wired into
  `pdf_reader.py::extract` (wraps `pdf_text_extraction` and, when
  triggered, `ocr_fallback` as two separate stages) and
  `pipeline.py::parse_one_resume` (wraps `llm_extraction`). Directly
  answers RELIABILITY_SCALE_ANALYSIS.md Section 1.2's "impossible to say
  from logs where the time went" gap.
- `src/matching/scorer.py`: distinct, higher-priority reasoning bullet when
  `llm_call_failed` is true ("AI extraction failed... this is not a real
  assessment"), instead of the generic "resume only partially parsed" text
  used for genuinely thin content. Both early-return and main-return paths
  of `score_candidate` now pass `llm_call_failed` through into
  `ScoreResult`.
- `src/matching/shortlist.py`: `llm_call_failed` added to every row shape
  (shortlist, reserve, needs_review) unconditionally, plus a new
  `summary.llm_extraction_failures` count.
- `src/output/report.py::write_parse_quality_report`: new "AI Extraction
  Failed" column, distinct from the Status/Method columns, plus the
  batch-level warning rendered at the top of the markdown file when the
  threshold is crossed.
- `app.py::api_run`: `details[...]` now includes `llm_call_failed` /
  `llm_failure_reason` for the candidate-detail view, and the top-level
  JSON response gains an `llm_warning` key (null when the batch is
  healthy).
- `templates/index.html` / `templates/candidate.html`: minimal, explicitly
  unstyled (per REBUILD_PROMPT.md Section 1) structural additions — a
  per-candidate `badge-llm-failed` badge, a failure-reason line on the
  detail page, and a batch-level warning banner (`data-testid`s added so a
  later automated browser test can target them without relying on visual
  styling that doesn't exist yet).

### Problems faced
None that required rework — this milestone's design was locked in
`REBUILD_PLAN.md` before any code was written (per the process rule), so
implementation matched the plan directly. The one thing worth recording:
initially considered gating `llm_call_failed` only into the `Partial`
branch's reasoning text, but realized `score_candidate`'s early-return
branch (for `parse_status == "Failed"`) also needed to pass the field
through explicitly rather than relying on the dataclass default — a
`Failed` parse today always has `llm_call_failed=False` (it fails before
ever reaching the LLM call), but leaving that implicit would have made a
future code path that fails *after* an LLM attempt silently wrong. Fixed
before ever being a bug, not after — covered by
`test_failed_parse_still_passes_through_llm_call_failed_field`.

### Test failures and how they were resolved
No test failed and required a fix — all new tests passed on first run.
Worth recording explicitly, though, what was verified rather than assumed:
the real-network test
(`test_real_invalid_groq_key_produces_llm_call_failed_not_a_crash`) was
first run with a plain assertion on `llm_call_failed`, then re-run with the
actual failure reason printed to confirm it was a genuine `HTTP 401:
Invalid API Key` response from Groq's real API — not a connection failure
(e.g. no network in the sandbox) being misclassified into the same boolean.
Confirmed: `reason: HTTP 401: {"error":{"message":"Invalid API
Key",...}}`, and the literal invalid key string never appears in that
reason.

### Final test results
- Unit: `tests/test_scorer.py` (+1 new test), `tests/test_shortlist.py`
  (new file, 4 tests), `tests/test_timing.py` (new file, 3 tests) — all
  passing.
- Integration / LLM-pipeline-specific: `tests/test_pipeline.py` (new file,
  13 tests) — covers simulated 429, simulated 500, simulated timeout,
  simulated malformed-JSON-shape response (all via mocked
  `requests.post`), a full-pipeline simulated outage test, the exact
  3-poisoned-resumes regression scenario from
  RELIABILITY_SCALE_ANALYSIS.md Section 1.1, and one real (non-mocked)
  network call against Groq with a deliberately invalid key.
- Full suite: `pytest tests/` — 50/50 passing (29 pre-existing + 21 new),
  0.64s.
- Manual/structural: Flask test client confirms `GET /`, `GET /candidate`,
  `GET /api/jds` all return 200 after the template changes; `node --check`
  confirms both templates' `<script>` blocks are still syntactically valid
  JS after the badge/banner additions.

### Notes for future milestones
- `summarize_llm_failures()` and `LLM_FAILURE_BATCH_WARNING_THRESHOLD` live
  in `src/pipeline.py` — Milestone 2's dual-provider failover should raise
  `LLMError` (setting `llm_call_failed`/`llm_failure_reason` the same way)
  only after *both* Groq and Gemini have been tried, so this milestone's
  batch-warning logic keeps working unchanged, without needing to know
  which provider(s) were attempted.
- `src/timing.py`'s `get_recorded_timings()` is process-global and
  in-memory, matching the project's "in-memory is enough" decision —
  Milestone 8's load test should call `clear_recorded_timings()` before a
  batch run to get a clean per-run timing set, and can read the results
  back directly rather than parsing log output.
- The frontend badge/banner elements added here use `data-testid`
  attributes specifically so Milestone 9's structural frontend tests (and
  any later browser automation) can select them reliably without depending
  on the visual CSS classes, which are explicitly out of scope until the
  later UI/UX phase.

### Recurring-risk issues
- **A provider auth failure (401) is not in `RETRYABLE_STATUS_CODES`
  `{429,500,502,503,504}`, so it fails fast with no backoff delay** —
  confirmed directly (the real-key test completed in well under a second).
  This is correct behavior (retrying a bad key 4 times with backoff would
  be pure wasted latency), but worth knowing explicitly: if a future
  session sees a suspiciously *fast* `llm_call_failed=True`, that's
  consistent with an auth/config problem, not a timeout/rate-limit —
  the `llm_failure_reason` string will say which.

---

## Milestone 2: Concurrency retune, Groq→Gemini failover, content-hash cache — 2026-07-20

### Goal
Concurrency is set against Groq's real measured 12K TPM ceiling (not a
guessed RPM number), Gemini is used as an automatic per-request failover
(not a load-bearing second lane), and identical file bytes are never
re-sent to the LLM twice in the same server process.

### What was done
- `src/ai_client.py`: added `call_llm_with_failover(system, user,
  json_mode, primary, fallback)` -- tries `primary` (default: `AI_PROVIDER`
  env or "groq"), and on `LLMError` tries `fallback` (default:
  `AI_FALLBACK_PROVIDER` env or "gemini") once before giving up. Both
  failing raises one `LLMError` mentioning both providers' reasons
  (scrubbed of secrets, same as every other `LLMError` in this codebase).
  `call_llm` itself is unchanged and still the single-provider primitive.
- `src/extraction/llm_extract.py` and `src/llm_jd_extract.py` both switched
  from `call_llm` to `call_llm_with_failover` -- applied to both resume
  extraction and free-text JD extraction for consistency (a JD-parsing
  failure shouldn't behave differently from a resume-parsing failure).
- `src/pipeline.py`: added `DEFAULT_MAX_WORKERS = 6`, replacing the old
  hard-coded 4, with the exact TPM math documented inline (12,000 TPM ÷
  ~1,200-2,100 tokens/call ≈ 6-9 sustainable req/min -- the real
  constraint, not the 30 RPM ceiling the original number was sized
  against). Added `run_batch(paths, max_workers=None)` -- a shared,
  order-preserving, bounded-concurrency batch executor using
  `ThreadPoolExecutor` + `as_completed()` (schedules identically to the
  old `.map()` call; the real difference is `as_completed()` gives
  Milestone 3's future progress-polling something to observe as results
  land, which `.map()` doesn't expose). `app.py` now calls `run_batch`
  instead of its own inline `ThreadPoolExecutor.map()` -- one shared batch
  executor, not two.
- `src/pipeline.py`: added SHA-256 content-hash caching
  (`_RESUME_CACHE`, `clear_resume_cache()`). `parse_one_resume` is now a
  thin cache-check wrapper around the real logic, renamed
  `_parse_one_resume_uncached`. Deliberately never caches a result where
  `llm_call_failed=True` -- a rate limit or transient outage is not a
  property of the file's content, and caching it would turn a retryable
  transient error into a permanent one for that file's lifetime in the
  process. Only genuinely content-derived results (Clean, real-content
  Partial, or hard Failed) are cached.

### Problems faced
The first ad hoc real-batch verification run (see Test failures section)
appeared to show every resume failing AI extraction in ~0.1ms -- looked
alarming at first glance. Root-caused immediately: the verification script
imported `src.pipeline` directly without calling
`src.env_loader.load_env()` first, so `GROQ_API_KEY`/`GEMINI_API_KEY` were
never loaded from `.env` into `os.environ`, and the call failed instantly
on "GROQ_API_KEY is not set" -- not a real provider or code problem, just
the script skipping a step `main.py`/`app.py` both do automatically at
import time. Re-ran with `load_env()` called first; real results below.
Recorded here specifically so a future session doesn't re-diagnose the
same "why did everything fail in 0ms" symptom as a code bug.

### Test failures and how they were resolved
One test failure during development, fixed before commit:
`test_identical_content_is_a_cache_hit_and_skips_reparsing` initially
mocked `_parse_one_resume_uncached` with a fixed `return_value` (a
`ParsedResume` with a hard-coded filename), which doesn't match how the
real function behaves (it always sets `file_name` from the argument it was
called with). This made the test's own mock the source of a filename
mismatch, not a real bug in `parse_one_resume`. Fixed by switching the
mock to a `side_effect` function that actually uses the passed `file_name`
argument, matching real behavior -- re-ran, passed. Recorded here because
it's a reminder that a mock with a fixed `return_value` can silently drift
from what the real function does; `side_effect` functions that mirror the
real signature are safer for this kind of cache-correctness test.

### Final test results
- Unit: `tests/test_ai_client_failover.py` (new, 4 tests) -- primary
  success never touches fallback, primary failure triggers fallback and
  fallback succeeds (confirmed via call-order assertion, not just the
  final return value), both-fail raises one error mentioning both
  providers, no-fallback-configured preserves old single-provider
  behavior unchanged.
- Unit: `tests/test_resume_cache.py` (new, 4 tests) -- identical content
  hits cache and skips re-parsing (filename still corrected per-call),
  different content never collides, an `llm_call_failed=True` result is
  never cached (re-parses every time), and a result that succeeds *after*
  a prior failure gets cached correctly from that point on.
- Load/concurrency (synthetic, no LLM calls, matching the project's
  existing verification pattern): `tests/test_run_batch.py` (new, 4
  tests) -- order preservation despite deliberately-reversed completion
  order, a tracked-concurrency test proving the `max_workers` ceiling is
  real (never exceeded, and genuinely > 1, not accidentally serialized),
  empty-input handling, and the default worker count respecting
  `DEFAULT_MAX_WORKERS`.
- Full suite: `pytest tests/` -- 61/61 passing (50 from Milestones 0-1 +
  11 new), ~1.1s.
- Real, non-mocked integration verification (ad hoc script, not a
  committed slow test -- results recorded here per the plan's "real calls
  are fine" decision): 3 real resumes from `data/real_resumes/` through
  `run_batch()` with real Groq credentials -- all three completed
  Clean/`llm_call_failed=False` with correctly extracted names and
  skills (e.g. "Siddharth Rao", skills ["Dart", "Kotlin", "JavaScript"]).
  Total wall-clock: 1.0s for 3 resumes, with each resume's
  `llm_extraction` stage individually timed at ~1000ms -- confirming the
  three LLM calls genuinely overlapped (concurrent), not ran sequentially
  (which would have taken ~3s). Separately, real failover verification:
  set `GROQ_API_KEY` to a deliberately invalid value while leaving the
  real `GEMINI_API_KEY` in place -- `parse_one_resume` still returned
  `llm_call_failed=False` with a correctly extracted name ("SIDDHARTH
  RAO"), confirming the Gemini fallback fired for real and actually
  recovered the call, not just in the mocked test.

### Notes for future milestones
- `run_batch()` is the shared batch-execution entry point Milestone 3's
  async job architecture should build on -- the `as_completed()` loop
  inside it is exactly where a `job_id`'s progress state should be updated
  as each resume finishes, rather than writing a second, parallel
  concurrency implementation for the job-polling endpoint.
- `DEFAULT_MAX_WORKERS = 6` is a starting point, explicitly flagged in its
  own comment as subject to correction by Milestone 8's real 40-resume
  load test -- if that test shows 429s slipping through or throughput
  different from the ~6-9 req/min prediction, retune the constant there
  and document the correction, don't silently leave a stale number.
- `main.py`'s CLI batch loop is still fully sequential (unchanged in this
  milestone) -- `run_batch()` exists and is shared-module-ready if a
  future milestone decides to parallelize the CLI path too, but that was
  not in this milestone's scope (RELIABILITY_SCALE_ANALYSIS.md only
  flagged the web app's concurrency, not the CLI's).

### Recurring-risk issues
- Any ad hoc script or test that imports `src.pipeline` (or anything
  that eventually calls `src.ai_client.call_llm`) directly, without first
  calling `src.env_loader.load_env()`, will see every LLM call fail
  near-instantly with "GROQ_API_KEY is not set" -- easy to misread as a
  real provider/network problem. `main.py` and `app.py` both call
  `load_env()` automatically at import time, so this only bites ad hoc
  scripts/REPL sessions. Solution: always call `load_env()` first in any
  standalone script that touches the LLM pipeline directly.
- A resume's `llm_call_failed=True` result must never be written into
  the content-hash cache -- already handled (see "What was done"), but
  worth restating as a standing invariant: any future change to
  `parse_one_resume`'s caching logic must preserve this check, or a
  transient rate-limit blip could get "stuck" as a permanent failure for
  that file's content hash until the process restarts.

---

## Milestone 3: Async job architecture with progressive results — 2026-07-20

### Goal
`/api/run` returns immediately with a `job_id`; a polling endpoint returns
candidates as they finish, in bounded-concurrency waves, so the browser
shows real progress instead of blocking on the whole batch — and survives
a slow batch without hitting a reverse-proxy timeout on a free host.

### What was done
- `src/jobs.py` (new): `JobStore` / `JobState` -- in-memory, thread-safe
  (single `threading.Lock`) async job store. `job_id` is `uuid.uuid4().hex`
  (unguessable, not enumerable). TTL-based eviction (`JOB_TTL_SECONDS`,
  default 2 hours) prunes stale job records on every store access, bounding
  both memory growth and how long extracted resume PII sits in server
  memory. `error_message` is always a pre-written generic string, never a
  raw exception.
- `src/pipeline.py::run_batch`: extended with an optional `on_result`
  callback, fired the instant each resume finishes (used by the job runner
  to push incremental progress), and now catches an unexpected
  (non-`LLMError`) exception per-resume, degrading just that one resume to
  a `Failed` parse instead of letting it crash the entire batch -- matters
  more now that batches run unattended in a background thread with no
  request handler left to catch a batch-wide crash.
- `app.py::api_run`: no longer runs the batch synchronously. Validates the
  upload exactly as before, saves files under a `tempfile.mkdtemp()`
  directory (not `TemporaryDirectory()`, whose context-manager cleanup
  would fire the instant the request returns -- before the background job
  even starts), creates a job via `job_store.create()`, starts a daemon
  `threading.Thread` running `_execute_job`, and returns `{job_id, total}`
  with HTTP 202.
- `app.py::_execute_job` (new): runs `run_batch` with an `on_result`
  callback that scores each resume as it completes and appends a
  lightweight progress row to the job store. On completion, builds the
  same final payload shape the old synchronous `/api/run` returned
  (`jd`/`result`/`details`/`llm_warning`, via the extracted
  `_build_candidate_details` helper) and calls `job_store.mark_done`. On
  any exception, logs the real detail server-side and calls
  `job_store.mark_error` with a generic message only.
- `app.py`: two new routes -- `GET /api/run/<job_id>/status` (progress:
  status/completed/total/candidates_so_far) and
  `GET /api/run/<job_id>/result` (final payload once done; 409 while
  running, 500 with the generic error message if the job errored, 404 for
  an unknown/expired job_id -- same response whether the ID never existed,
  already aged out, or is malformed, so no information is leaked about
  which).
- `MAX_FILES_PER_REQUEST` raised from 60 to 80, re-justified: since the
  request no longer runs the batch synchronously, the cap is now purely an
  upload-sanity/LLM-quota-exposure limit, not a timeout-avoidance measure.
- `app.run(...)` gained `threaded=True` -- required now that the Flask
  process must keep serving status polls and new job submissions while a
  background thread is mid-batch.
- `templates/index.html`: real `<progress>` element (`data-testid`s for
  future automation) driven by polling, a `pollJob()` loop
  (`/status` every 1.5s), and `renderInProgress()` which renders whatever
  candidates have completed so far, sorted by score, using the exact same
  `renderCandidate()` function the final results view uses -- no second
  rendering implementation. Results are only replaced once new real data
  arrives (progress or a finished result), never cleared just because a
  new run started, per the user's explicit requirement.

### Problems faced
Two real bugs found and fixed during this milestone's own test-writing
(not pre-existing, both introduced and caught within this milestone):

1. **Leaked background threads racing across tests.** Several of the new
   Flask-integration tests started a background job (via a mocked
   `app.run_batch`) but let their `with patch(...)` block exit before the
   job actually finished. Since `_execute_job` resolves `run_batch` and
   `job_store` as module globals *at call time*, a thread still running
   after the patch reverted would fall back to the REAL `run_batch` (a
   real, unmocked Groq/Gemini call) and the REAL shared `job_store`,
   racing against whatever the next test patched in. Symptom: intermittent
   failures with no obvious connection to the actual test logic. Fixed by
   adding a shared `_wait_for_terminal()` test helper and updating every
   test in `tests/test_app_async_jobs.py` to drain its job to a terminal
   state before its `with patch(...)` block exits -- documented directly
   in the helper's docstring so this can't be quietly reintroduced by a
   future test that forgets to drain.
2. **A real ordering race between cleanup and the "done" status becoming
   visible.** `_execute_job` originally called `job_store.mark_done(...)`
   inside the `try` block and `shutil.rmtree(tmp_dir, ...)` in a `finally`
   block that ran after. That meant a poller could observe `status="done"`
   in the small window before the `finally` block actually ran --
   `tests/test_temp_file_cleanup.py` caught this directly and
   deterministically (not flaky -- failed 3/3 runs before the fix, 4/4
   passed after): asserting `not os.path.exists(tmp_dir)` immediately
   after seeing `status == "done"` failed because the directory was still
   there. Fixed by reordering: `shutil.rmtree()` now runs BEFORE
   `job_store.mark_done()` (and before `mark_error()` on the failure path)
   -- "done" or "error" becoming visible to any poller is now a real
   guarantee that the uploaded PII is already gone, not a race.

### Test failures and how they were resolved
Covered in detail above (Problems faced) -- both were genuine bugs this
milestone's own tests caught before being logged as done, not
pre-existing issues rediscovered later. Re-ran the full suite 4 times in a
row after both fixes to confirm the flakiness was actually gone, not just
not-reproduced-this-time: 83/83 passing, all 4 runs.

### Final test results
- Unit: `tests/test_jobs.py` (new, 9 tests) -- UUID4 job_id shape, 200
  real creations with zero collisions, unknown-ID lookups return None not
  an exception, progress accumulation, terminal-state transitions, error
  messages are always strings (never containing "Traceback"), TTL
  eviction (both "does evict when stale" and "does not evict when fresh"),
  and no-op behavior (not a crash) for operations on an unknown job_id.
- Integration (Flask test client, `app.run_batch` mocked -- no real LLM
  calls): `tests/test_app_async_jobs.py` (new, 12 tests) -- fast
  non-blocking POST, status/result reflecting a completed job with the
  same top-level shape the old synchronous response had, progressive
  candidate delivery before the job finishes (direct regression test for
  the user's "8 move forward and show, others join as they finish"
  requirement), generic 404 for unknown job IDs, 409 while running, no
  stack-trace/secret leakage in an error job's result, upload validation
  unchanged (no files / too many files / missing JD), non-PDF files still
  silently skipped, and a path-traversal filename test confirming
  `secure_filename()` still prevents any saved file from escaping the
  generated temp directory.
- Security / PII lifecycle (real filesystem, no mocking of
  `shutil`/`tempfile`): `tests/test_temp_file_cleanup.py` (new, 2 tests)
  -- temp dir is deleted after a successful job AND after a crashed job;
  this is what caught the ordering race described above.
- Full suite: `pytest tests/` -- 83/83 passing (61 from Milestones 0-2 +
  22 new; the one real-network Milestone-1 test is excluded from this
  count when run via `-k "not real_invalid_groq_key"` but still passes
  independently), consistently across 4 repeated runs, ~2.0s.
- Real, non-mocked end-to-end verification: 4 real resumes through the
  full async flow (`POST /api/run` -> poll `/status` -> `/result`) against
  real Groq. `POST` returned the job_id instantly; polling showed
  `completed` genuinely climbing from 0/4 to 4/4 with real candidate names
  arriving mid-run (before `status` flipped to `done`); all 4 real LLM
  calls overlapped (each ~910-965ms, total wall-clock ~1.5s, not ~4s) --
  confirming real concurrency inside the async path, not just the
  synchronous one already verified in Milestone 2; `llm_warning` was
  `null` (healthy batch); final shortlist had all 4 candidates.

### Notes for future milestones
- Milestone 4 (persistent run history) should read the same
  `job.result` shape `_execute_job` already produces -- no new
  serialization needed, just write it to SQLite once a job reaches "done".
- Milestone 6/8's fixture and load tests can now exercise the real async
  path end-to-end (as demonstrated in this milestone's own real-4-resume
  verification) instead of needing a separate code path.
- The client-side "chunk large batches transparently" part of this
  milestone's original scope (REBUILD_PLAN.md Milestone 3) was NOT built
  as multi-job merging -- properly combining several chunk-jobs into one
  coherent shortlist would need a server-side "merge these job results and
  re-run build_shortlist over the union" endpoint (recomputing rank/cutoff
  requires the whole candidate set at once), and doing it client-side
  would violate WEB_APP_PLAN.md Section 6's "no scoring logic in the web
  layer" rule. Deferred, not silently dropped: `MAX_FILES_PER_REQUEST=80`
  comfortably covers the real ~54-resume dataset and the stated "up to 40"
  target in a single job, so this gap is unlikely to be hit in practice at
  this project's actual scale -- but if a genuinely >80-resume batch is
  ever needed, build the server-side merge endpoint rather than a
  client-side workaround.

### Recurring-risk issues
- **Any test that starts a background job via a mocked `app.run_batch`
  MUST drain it to a terminal state (`_wait_for_terminal()` in
  `tests/test_app_async_jobs.py`) before its `patch()` context exits.**
  Skipping this reintroduces the leaked-thread race described above --
  the symptom is intermittent, hard-to-reproduce test failures that look
  unrelated to whatever test is actually failing, because the real cause
  is a DIFFERENT test's straggler thread. If this class of flakiness
  resurfaces, check for a new test that starts a job without draining it,
  before assuming it's a new bug.
- **Any code that both writes a job's terminal status AND performs cleanup
  must do the cleanup FIRST.** A poller treats `status in ("done",
  "error")` as "safe to assume this job's side effects are fully settled"
  -- if that's ever not true (e.g. a future milestone adds another
  post-completion side effect), apply the same ordering fix: side effect
  before status update, not after.

---

## Security audit pass (Milestones 0-3) — 2026-07-20

Pulled forward from REBUILD_PLAN.md's Milestone 7 at the user's explicit
request ("make sure to do security check... no data leaks... no private
data accessible by hackers") rather than waiting until all feature
milestones were done. Scope: everything built so far (Milestones 0-3).
Milestone 7 will still run later for the parts that only make sense once
the whole rebuild is feature-complete (full lint/dead-code pass across the
final codebase), but the security-specific checks below are done now, not
deferred.

### Goal
Verify, with real evidence, that the system as it stands today does not
leak secrets, does not leak server-internal detail (paths/tracebacks) to
the browser, correctly minimizes and protects candidate PII, resists
prompt injection, and has no known-vulnerable dependencies.

### What was done
1. **Dependency vulnerability scan (`pip-audit -r requirements.txt`).**
   Found 22 known CVEs across 5 packages at their previously-pinned
   versions: Pillow 10.4.0 (PYSEC-2026-165 and 11 related image-processing
   CVEs), requests 2.32.3 (PYSEC-2026-1872, 2275), Flask 3.0.3
   (PYSEC-2026-2151), Werkzeug 3.0.4 (5 separate CVEs), pytest 8.3.3
   (PYSEC-2026-1845). Bumped every affected package to the lowest version
   `pip-audit` reported as fixed: Pillow 12.3.0, requests 2.33.0, Flask
   3.1.3, Werkzeug 3.1.6, pytest 9.0.3. Re-ran the full test suite after
   the bump (95/95 passing, no breakage) and re-ran `pip-audit` -- now
   reports "No known vulnerabilities found."
2. **Real, non-mocked test: uploading a `.pdf`-named file with invalid PDF
   content.** Handled gracefully (no crash, correctly routed to
   `needs_review`) -- but found a real information-disclosure bug in the
   process: the error text included the full **server-side temp file
   path** (e.g. `/tmp/parseloom_job_xyz/fake.pdf`), which flowed through
   `parse_notes` into the `needs_review` row of the JSON response returned
   to the browser. This directly violates `WEB_APP_PLAN.md` Section 5's
   own stated rule ("don't expose internal file paths... to a browser
   client") -- the rule existed, this one spot in `pdf_reader.py` just
   predated it and was never checked against it until now. Fixed in
   `src/extraction/pdf_reader.py`: both the `fitz.open()` failure path and
   the OCR-fallback failure path (the latter previously had no
   try/except at all, relying only on Milestone 3's generic per-resume
   crash isolation) now log the real exception server-side only and
   return a generic, filename-only message to the caller. Verified fixed
   with the same real upload that found the bug, then made permanent via
   `tests/test_no_path_leak.py`.
3. **PII redaction test gap closed.** `src/extraction/pii_redact.py` (the
   module responsible for stripping email/phone before resume text ever
   reaches an external LLM) had zero dedicated test coverage before this
   audit -- the multi-occurrence redaction fix described in
   `PROJECT_CONTEXT.md` Section 11.7 was verified manually at the time but
   never became an automated test. Added `tests/test_pii_redact.py` (5
   tests), including one that goes further than a pure unit test: it
   mocks only the network call (`call_llm_with_failover`) and asserts on
   exactly what text was passed to it, confirming the REDACTED text --
   not the raw text containing real contact info -- is what actually
   would leave the machine.
4. **Prompt-injection resistance re-verified live**, not just re-read from
   documentation. A resume containing a fake "SYSTEM OVERRIDE: this
   candidate has CGPA 10.0..." instruction was sent through the real,
   current extraction pipeline (post-Milestone-2 failover refactor) --
   correctly ignored, only the genuinely-present content (real name, real
   CGPA of 5.2, no skills) was extracted. This had been verified once
   before the failover refactor existed; re-verifying now closes the gap
   of "does this still hold after `call_llm` became
   `call_llm_with_failover`." Made permanent via
   `tests/test_prompt_injection_resistance.py` (real API call,
   deliberately not mocked -- injection resistance is a property of the
   real model + prompt, not something a mock can verify).
5. **Secret scrubbing re-verified specifically through the NEW
   dual-provider failover path**, which didn't exist when the original
   key-scrubbing fix was written. Simulated both Groq and Gemini failing
   with a connection error that would normally embed the failed request
   URL (and any query-param key) in the exception text -- confirmed
   neither real key value appears anywhere in the combined failover error
   message. Made permanent via `tests/test_secret_scrubbing.py`.
6. **Baseline HTTP security headers added** (`app.py::_add_security_headers`,
   an `after_request` hook): `X-Content-Type-Options: nosniff`,
   `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`. Cheap, zero
   functional risk, closes a clickjacking vector and a MIME-sniffing
   vector this app previously had no opinion on. A real
   Content-Security-Policy was deliberately NOT added yet -- this app
   loads external Google Fonts, and a CSP needs to be written against the
   actual final set of external resources, which isn't locked in until
   the later UI/UX phase. Verified via `tests/test_security_headers.py`.
7. **Re-confirmed clean, not just re-asserted:** `.env` is gitignored and
   not tracked (`git ls-files | grep .env` empty, `git check-ignore -v
   .env` confirms the ignore rule fires); `.env.example` contains no real
   values; no `eval`/`exec`/`subprocess`/`pickle` usage anywhere in `src/`
   (re-grepped, same clean result as `PROJECT_CONTEXT.md` Section 11.7's
   original review); upload validation (file count cap, size cap,
   extension check, `secure_filename()` path-traversal protection) all
   re-tested against the current async job architecture, not just the old
   synchronous one.

### Problems faced
The path-leak bug (item 2 above) was found by actually trying a real
malformed upload, not by reading the code and reasoning about it --
worth noting as a process point: `str(exc)` on a caught exception looking
"probably fine" is not the same as verifying what it actually contains.
The fix pattern (log real detail server-side, generic message to the
caller) already existed everywhere else in this codebase
(`ai_client.py::_scrub_secrets`, every `except Exception` block in
`app.py`) -- this one function in `pdf_reader.py` had just never been
checked against that same standard until this audit.

### Test failures and how they were resolved
No test failed after being written -- in every case here, the "failure"
was found by manual/ad hoc investigation (real uploads, real API calls)
BEFORE a permanent test was written, then the permanent test was written
to lock in the fix. This is the reverse order of a normal TDD red/green
cycle, worth recording explicitly: for security findings, "explore first
with a throwaway script, fix, then write the permanent regression test"
is a reasonable order when the bug isn't yet known to exist -- writing a
test for a bug you haven't found yet isn't possible.

### Final test results
- New security-specific test files this pass: `tests/test_no_path_leak.py`
  (2), `tests/test_pii_redact.py` (5), `tests/test_prompt_injection_resistance.py`
  (1, real API call), `tests/test_secret_scrubbing.py` (2),
  `tests/test_security_headers.py` (1) -- 11 new tests total.
- `pip-audit -r requirements.txt`: 0 known vulnerabilities (was 22 before
  the dependency bump).
- Full suite: `pytest tests/` -- 95/95 passing (including the real-network
  Milestone-1 test), ~2.5s.

### Notes for future milestones
- Milestone 4 (persistent run history / SQLite) will need its own security
  pass once built -- specifically, confirm `result_json` written to SQLite
  never contains a raw path or key (the same class of bug found in item 2
  above), since that's new persistent storage this audit didn't cover
  (it didn't exist yet).
- Milestone 7's later full pass should re-run `pip-audit` again right
  before final submission (dependency CVE databases update continuously;
  "clean" today doesn't mean "clean in a week").
- A Content-Security-Policy header is deliberately still missing --
  revisit once the UI/UX phase locks in its final set of external
  resources (fonts, any CDN-hosted component libraries per
  `REBUILD_PROMPT.md` Section 6).

### Recurring-risk issues
- **Any code that catches an exception and includes `str(exc)` (or an
  f-string embedding the exception directly) in a message that could
  reach an API response must be checked for what that exception actually
  contains, not assumed to be safe.** `fitz`/PyMuPDF's exceptions embed
  the full file path; provider SDK/`requests` exceptions can embed request
  URLs (and therefore query-param secrets, if a provider is ever added
  that puts a key in the URL again). The established pattern -- log real
  detail server-side via `logger.exception`/`logger.warning`, return a
  generic message -- must be applied at every single catch site, not just
  the ones that happened to get attention. **A finding worth flagging
  explicitly to the user, not silently decided:** `output/sample_output.json`
  and `output/parse_quality_report.md` are tracked in git (per
  `.gitignore`'s explicit exception, since `PROJECT_CONTEXT.md` documents
  them as required submission deliverables) and contain real candidate
  names and name-bearing filenames from the real 54-resume event dataset
  (e.g. "Aditya Kulkarni", `App_Developer_Resume_1_Siddharth_Rao.pdf`) --
  no emails or phone numbers (those are never in the output shape at all),
  but real names nonetheless. If this repository is or becomes public on
  GitHub, that's real candidate PII published publicly. `SESSION_HANDOFF.md`
  already flagged the repo's public/private status as unconfirmed. This
  wasn't something introduced by this rebuild and isn't something to fix
  unilaterally (these are explicitly required, already-graded submission
  files) -- it needs a decision from the user: confirm the repo stays
  private, or regenerate these two files from a synthetic/anonymized
  dataset before any future public push.

---

## Addendum to security audit: repo-visibility finding resolved — 2026-07-20

The prior entry's "Recurring-risk issues" section flagged that
`output/sample_output.json` and `parse_quality_report.md` are tracked in
git and contain real candidate names from the event dataset, and that this
matters if the repo is public. Asked the user directly rather than
assuming either way.

**User's answer: the repo is intentionally public, deliberately, for
future purposes (e.g. portfolio/resume-visibility for the user
themselves).** This is a confirmed, informed decision, not an oversight --
recorded here so a future session doesn't re-raise this as an open
question or "fix" it unilaterally (e.g. by scrubbing names out of the
required submission files, which would also risk breaking their
documented "confirmed against real 54-resume dataset" provenance). No code
or file changes made as a result of this answer -- purely a
decision-recorded entry.

---

## Excel export: download any completed run as .xlsx — 2026-07-20

Built ahead of Milestone 4 (persistent run history) at the user's request,
deliberately sequenced first: immediately useful the moment it exists
(works for any live job today), and designed so Milestone 4 can reuse the
exact same export function for a historical run later without rework --
recommended this ordering explicitly rather than silently picking one.

### Goal
Any completed run's full data (Shortlist, Reserve, Needs Review, and
per-candidate detail) can be downloaded as a real, editable .xlsx file --
the user can open it in Excel/Sheets and sort, filter, or edit it however
they want, independent of the web app.

### What was done
- Added `openpyxl==3.1.5` to `requirements.txt` (pure-Python, no native
  binary dependency, fits the project's minimal-deps philosophy).
- `src/output/xlsx_export.py` (new): `build_workbook(payload)` takes the
  exact same dict shape `/api/run/<job_id>/result` already returns as
  JSON and produces a 4-sheet workbook (Summary, Shortlist, Reserve, Needs
  Review) -- bold headers, frozen header row, auto-sized columns, detail
  fields (college/degree/CGPA/skills/skill-match breakdown) flattened in
  alongside the score/confidence/reasons columns already shown in the web
  UI. No new scoring/parsing logic (WEB_APP_PLAN.md Section 6) -- this
  module only serializes data that already exists.
- `app.py`: new `GET /api/run/<job_id>/export.xlsx` route, same
  404/409/500 status-code contract as `/result` (unknown job, still
  running, job errored). Builds the workbook from `job.result`, streams it
  via `send_file` with the correct spreadsheet MIME type. Download
  filename is built from the JD role name via `secure_filename()` -- the
  role can originate from an LLM-extracted free-text JD (same trust
  boundary as resume content), so it's treated as untrusted input, not a
  safe string, before being placed into a `Content-Disposition` header.
- `templates/index.html`: a plain "Download as Excel (.xlsx)" link shown
  once a run finishes, pointing straight at the export route (no JS build
  step -- the browser handles the download natively). `job_id` is now
  stashed onto the resolved result object in `pollJob()` so the results
  view has it available without a second lookup.

### Problems faced
None requiring rework. The one design decision worth recording: the
export route's status-code contract was deliberately made identical to
`/api/run/<job_id>/result`'s (404/409/500 in the same cases) specifically
so a future client integration doesn't need new error-handling logic just
because it's asking for a spreadsheet instead of JSON.

### Test failures and how they were resolved
None -- all tests passed on first run.

### Final test results
- Unit: `tests/test_xlsx_export.py` (new, 7 tests) -- all four sheets
  present, Summary sheet contains the JD name and counts, Shortlist sheet
  has the correct header and correctly flattens detail fields (college,
  skills) alongside score data, Reserve sheet includes the
  "Below CGPA Minimum" column, Needs Review sheet has file+reason, an
  empty payload (zero candidates) produces valid header-only sheets rather
  than crashing, and the produced bytes are confirmed to be a genuine
  loadable .xlsx (magic bytes `PK`, reloaded successfully via
  `openpyxl.load_workbook`).
- Integration (Flask test client): `tests/test_app_xlsx_export_route.py`
  (new, 4 tests) -- 200 with correct MIME type and attachment header for a
  completed job, 404 for an unknown job, 409 while still running, and a
  dedicated security test confirming a JD role containing path-traversal
  and header-injection characters (`'../../evil"; filename="hacked.txt'`)
  produces a `Content-Disposition` header with no `..`, no `/`, and no
  stray unescaped quote that could break out of the filename attribute.
- Full suite: `pytest tests/` -- 106/106 passing.
- Real, non-mocked end-to-end verification: 3 real resumes through the
  full async job flow, real Groq extraction, exported via the real route,
  written to disk, and reopened with `openpyxl` independently of this
  app's own code -- confirmed real candidate names ("Siddharth Rao",
  "KAVYA MENON", "Varun Kapoor") and real scores present in the
  Shortlist sheet, not placeholder/stub data.

### Notes for future milestones
- Milestone 4 (persistent run history) should call this same
  `build_workbook()` for a historical run's stored `result_json` -- no new
  export logic needed, just a route that looks up a stored run instead of
  an in-memory job.
- `templates/candidate.html` does not get its own per-candidate export --
  only the batch-level Shortlist/Reserve/Needs-Review view does, since a
  spreadsheet's natural unit is "the whole run," not one candidate.

### Recurring-risk issues
- Same standing rule as the security audit entry: any value that
  ultimately reaches an HTTP header (here, the export filename via
  `Content-Disposition`) must be treated as untrusted if it can originate
  from JD/resume content, and run through `secure_filename()` or
  equivalent -- this route follows that rule already; any future
  download/export route must too.

---

## Milestone 4: Persistent run history (SQLite, per-client, concurrency-safe) — 2026-07-20

### Goal
A completed run can be reopened later ("5 days ago or 10 days ago or any
JD," per the user's own framing) by re-downloading the same Excel export
or by browsing a "Past Runs" list on the page that submitted it. The user
explicitly required this to work for real, concurrent, multi-user
production traffic ("make sure it can be used real time by users"), not
just single-operator local testing — this shaped every design decision
below.

### What was done
- `src/history.py`: new SQLite-backed persistence layer.
  `save_run()` / `list_runs_for_client()` / `get_run_for_client()` /
  `init_db()`. Two deliberate scope decisions, made explicit up front
  rather than left implicit:
  1. **Per-client ownership, not a global shared history.** This app has
     no login. Once it's genuinely public with more than one visitor at a
     time, a global run history would let any visitor browse every other
     visitor's uploaded resumes and extracted candidate data — undoing
     everything Milestones 1-3 did for PII protection. Every run is
     stored with a `client_id` (random, generated client-side, persisted
     in `localStorage`, validated server-side against
     `^[a-zA-Z0-9_-]{8,64}$`), and every read is both filtered AND
     ownership-checked against it.
  2. **Concurrency-safe for genuinely simultaneous users.** Every
     connection sets `PRAGMA journal_mode=WAL` and
     `PRAGMA busy_timeout=5000`, and a fresh short-lived connection is
     opened per operation rather than sharing one connection across
     threads (this app runs `threaded=True` plus background worker
     threads — a shared connection would be a real race).
- `app.py`: `_execute_job()` now accepts `client_id` and calls
  `history.save_run(...)` (guarded by `if client_id`) once a job
  succeeds. New routes: `GET /api/runs?client_id=` (list, newest first),
  `GET /api/runs/<run_id>?client_id=` (full result payload, same shape as
  `/api/run/<job_id>/result`), `GET /api/runs/<run_id>/export.xlsx?client_id=`
  (reuses `build_workbook()`/`workbook_to_bytes()` from the Excel-export
  milestone unchanged — no new export logic, per WEB_APP_PLAN.md Section
  6). All three enforce ownership via `get_run_for_client()`/
  `list_runs_for_client()`, never raw filtering.
- `templates/index.html`: `getOrCreateClientId()` generates a random ID
  once via `crypto.randomUUID()` (with a fallback for older browsers) and
  persists it in `localStorage`; sent as a `client_id` form field on every
  `/api/run` submission. New "Past Runs" section lists this browser's own
  history (fetched from `/api/runs`) and reopens any entry through the
  existing `renderResults()` — no separate rendering path for historical
  vs. live results. `renderResults()`'s Excel-download link now reads an
  explicit `payload.export_url` (set by `pollJob()` for a live run, or by
  the past-runs click handler for a historical one) instead of assuming
  `/api/run/<job_id>/export.xlsx` — a reopened historical run's in-memory
  job is long gone (`JobStore` has a TTL) by the time it's reopened, so it
  needs the `/api/runs/<id>/export.xlsx` route instead.
- `.gitignore`: added `instance/` — the SQLite DB is runtime data
  containing real candidates' extracted PII, same reasoning as
  `data/real_resumes/`, never committed.

### Problems faced

**Bug 1 — `save_run()`'s own error handling didn't actually catch every
storage failure.** `tests/test_history.py` (a new test asserting
`save_run()` never raises even when given a non-JSON-serializable
payload) caught this immediately: `except sqlite3.Error` only catches
SQLite-layer errors, but `json.dumps(result)` was being called inline
inside the `conn.execute(...)` call — a `TypeError` from a bad payload
propagated straight past the `except` clause, contradicting the
function's own documented guarantee ("never raise out to the caller on a
storage failure"). Fixed by serializing to `result_json` as its own
statement before the `with` block, and widening the `except` to
`(sqlite3.Error, TypeError, ValueError)`.

**Bug 2 — a real ordering race between `job_store.mark_done()` and
`history.save_run()`, caught only by the full test suite, not by any
individual test file.** `_execute_job()` originally called
`history.save_run(...)` *after* `job_store.mark_done(job_id, ...)`. Since
`mark_done()` is what makes `status="done"` visible to a poller, a fast
poller (exactly what `tests/test_app_history_routes.py`'s
`_wait_for_terminal()` helper is) could observe `"done"` and immediately
`GET /api/runs/<job_id>` in the small window before the next line
(`history.save_run`) had actually executed — a 404 for a run that had, in
fact, succeeded. `python3 -m pytest tests/test_app_history_routes.py -v`
alone passed every time (less contention, more slack for the background
thread to get scheduled); the same tests failed intermittently only when
run as part of the full suite (`python3 -m pytest -q`, 122 passed / 2
failed). This is the same class of bug as Milestone 3's cleanup-ordering
race, documented there as a standing rule: **"done"/"error" becoming
visible must guarantee every side effect associated with that state has
already happened, not just be likely to have happened.** Fixed by
reordering `_execute_job()` so `history.save_run()` runs *before*
`job_store.mark_done()`. Verified by running the full suite 3 consecutive
times after the fix (124/124 each run, no intermittent failures) — a
single passing run would not have been sufficient evidence for a race
condition fix.

**Bug 3 (real, sandbox-environment-specific, found only via a live,
non-mocked server) — SQLite WAL mode does not reliably work on this dev
sandbox's own working directory.** A genuine end-to-end test — starting
the real Flask dev server, uploading a real resume, and hitting
`/api/runs`, `/api/runs/<id>`, and `/api/runs/<id>/export.xlsx` with real
HTTP requests (not the mocked Flask test client) — surfaced
`sqlite3.OperationalError: disk I/O error` on every read, even
immediately after a successful write. Root cause: this dev sandbox's
working directory (where `instance/parseloom_runs.db` lives by default)
is a FUSE-mounted sync folder back to the user's own machine, and WAL
mode's `mmap`-backed `-wal`/`-shm` files are known to be unreliable on
FUSE/network-style filesystems — a genuine filesystem-capability gap, not
a logic bug. Confirmed by re-running the identical live-server test with
`PARSELOOM_HISTORY_DB_PATH` pointed at an ordinary local path
(`/tmp/parseloom_history_e2e/runs.db`) instead: full success end-to-end
(list, detail, export, and the cross-client ownership check all behaved
correctly), proving the read/write/ownership logic itself was correct all
along and the failure was purely about *where* the DB file lived. Two
fixes landed regardless of environment: (1) `DB_PATH` is now overridable
via `PARSELOOM_HISTORY_DB_PATH`, so a real deployment can point it at
whatever ordinary writable disk its host provides; (2)
`list_runs_for_client()` and `get_run_for_client()` now both catch
`sqlite3.Error` and degrade to `[]` / `None` (matching `save_run()`'s
existing philosophy) instead of letting a storage-layer exception surface
as a 500 — persistent history is a nice-to-have layered on top of the
already-working in-memory job result, and a transient disk hiccup reading
it back should never make the page look broken. Re-verified against the
*default* (FUSE-mounted) path after this fix: `/api/runs` and
`/api/runs/<id>` both now return clean 200/404 responses instead of 500,
while the live job's own `/api/run/<id>/result` (unrelated to history)
continued working throughout, confirming the degradation is scoped to
history alone and never touches the core run flow.

### Test failures and resolutions
- `test_save_run_never_raises_even_if_result_is_not_json_serializable`
  (new) — failed once (`TypeError` propagated), fixed per Bug 1 above,
  passed after.
- `test_get_run_returns_full_result_payload_for_the_owner` and
  `test_export_historical_run_returns_a_real_xlsx` (new, in
  `tests/test_app_history_routes.py`) — passed in isolation, failed
  intermittently (2/9 in that file) only as part of the full suite;
  root-caused and fixed per Bug 2 above; full suite re-run 3x clean after.
- No test file failures from Bug 3 — that bug only manifested against a
  real running server on this sandbox's actual filesystem, which is
  exactly why the real (non-mocked) end-to-end verification step was
  necessary and not redundant with the mocked test suite.

### Final test results
- `pytest tests/test_history.py` — 9/9, including
  `test_concurrent_writes_from_many_threads_all_succeed` (25 real OS
  threads, a `threading.Barrier` to maximize actual simultaneous
  contention, asserts zero errors and all 25 writes independently
  readable back) and `test_concurrent_reads_and_writes_do_not_corrupt_or_block`
  (20 threads, mixed simultaneous reads and writes) — this is the direct,
  concrete evidence behind the user's "make sure it can be used real time
  by users" requirement, not just a design-doc claim.
- `pytest tests/test_app_history_routes.py` — 9/9, including
  `test_client_a_cannot_read_client_bs_run_via_api` (client A, holding
  client B's real `run_id`, gets 404 on detail, an empty list, and 404 on
  export — the ownership check holds at the full HTTP-route level, not
  just inside `src/history.py`).
- Full suite: `pytest tests/` — 124/124 passing, 3 consecutive clean runs
  after the Bug 2 fix.
- Real, non-mocked end-to-end verification (twice — once against the
  default FUSE-mounted path to confirm the graceful-degradation fix, once
  against an ordinary local path to confirm full correctness): live Flask
  dev server, real resume upload, real Groq extraction, full
  upload → poll-to-done → history-list → history-detail →
  history-export-xlsx → cross-client-ownership-denied flow, all over real
  HTTP requests. The `/tmp`-path run produced a real, `openpyxl`-loadable
  `.xlsx` (`file` reported "Microsoft Excel 2007+") containing the real
  extracted candidate ("SNEHA GUPTA" / "Aditi"-named files from
  `data/random_mocks/`).

### Notes for future milestones
- Any future feature that writes to local disk (this DB, or anything
  similar) should default its path the same way `src/history.py` now
  does: computed relative to the app, but overridable via an env var —
  cheap insurance against exactly the class of environment-specific
  filesystem quirk Bug 3 was.
- The `payload.export_url` pattern in `templates/index.html` (an explicit
  field set by whichever code path produced the payload, rather than the
  rendering code guessing a URL from `job_id` alone) is worth reusing for
  any future case where the same rendered view can be reached from more
  than one data source with different backing routes.

### Recurring-risk issues
- Reconfirmed standing rule from Milestone 3: any state transition that a
  poller/client treats as "this is now safely readable" (`status="done"`,
  here also implicitly "history for this run now exists if it's going to
  exist at all") must have every one of its side effects complete
  *before* that state becomes visible, not after. This is the second time
  this exact class of bug has appeared (Milestone 3: cleanup vs. `done`;
  Milestone 4: history-save vs. `done`) — worth treating as a checklist
  item for any future state-transition code, not just something to catch
  reactively via the full suite.
- Storage-layer read paths (anything hitting disk on the read side of a
  request) should default to graceful degradation (empty/`None`/generic
  message) rather than propagating raw exceptions into a 500, mirroring
  the security-audit-era rule about never leaking raw exception detail —
  Bug 3 is a concrete instance of a class of risk (transient disk/lock
  failures) that will recur on any real host eventually, free-tier or
  not, and the code should already assume that.
  download/export route must too.

---

## Milestone 5: Cross-tab "Back to results" fix — 2026-07-21

### Goal
Clicking "Back to results" on the candidate detail page returns the user
to the original tab (via `window.close()`), not a re-render inside the
detail tab, with a documented fallback when the tab isn't opener-owned.

### What was done
This session opened by discovering the fix already existed in
`templates/candidate.html` (lines 83–86 as found) — added in the
pre-rebuild session per `SESSION_HANDOFF.md` item 7, before the
milestone-discipline system existed, so it had never been logged or
re-verified against the rebuilt codebase. Line-by-line review confirmed
it matches `REBUILD_PLAN.md`'s Milestone 5 spec in substance: `window.close()`
fires first, a `setTimeout(150ms)` fallback navigates to
`/#results-container` (an improvement over the plan's literal `/` —
scrolls straight to results instead of the hero) if close was silently
blocked. It doesn't literally check `window.closed` the way the plan's
prose describes, but that's not a gap: if `close()` succeeds, the tab's
JS execution stops before the timer fires; if blocked, execution
continues and the fallback fires. Same outcome, one fewer moving part.
The opener relationship it depends on (`index.html`'s `window.open()` for
the "View full details" button, not a plain link) was confirmed intact.
No code changes were needed for Milestone 5 itself.

### A real bug found in the same code path, fixed as part of this milestone
Not part of Milestone 5's literal scope, but found while reviewing the
exact code path Milestone 5 verifies, and flagged to the user per
`REBUILD_SESSION_HANDOFF.md`'s explicit instruction to surface — not
silently reconcile — any non-trivial interaction between Milestone 4
(history) and Milestone 5: reopening a historical run via the "Past Runs"
list (`templates/index.html`, the `pastRunsListEl` click handler) called
`renderResults(data)` but never wrote that payload to
`localStorage['parseloom_last_run']` — the only place `candidate.html`
read from at the time. Clicking "View full details" on a candidate from a
reopened past run showed either stale data from an earlier live run this
session, or "Candidate not found" if none had happened yet. Fixed by
persisting the payload to `localStorage` before rendering, mirroring the
live-run submit handler's existing order. Added
`tests/test_frontend_js_regression.py`: a `node --check`-based syntax
test for both templates' `<script>` blocks (using a real temp file, not
`/dev/stdin` — the latter failed with `ENOENT` against a pipe fd
specifically in this sandbox), plus a regression test that isolates the
past-run click handler's source text and asserts the `localStorage.setItem`
call exists and precedes `renderResults(data)`, matching the live-run
handler's ordering.

### Test failures and how they were resolved
`test_script_block_is_valid_js` initially failed on both templates:
`node --check /dev/stdin` raised `ENOENT: no such file or directory, open
'/proc/5/fd/pipe:[...]'` in this sandbox specifically. Fixed by writing
the extracted script to a real `tempfile.NamedTemporaryFile` and running
`node --check` against that path instead — portable, works identically
here and on a normal machine.

### Real, non-mocked verification
The exit criteria explicitly requires a real browser click-through — code
review and `pytest` alone can't verify actual tab-close/focus-return
behavior. The user ran it directly (their own machine, Safari): upload →
run → open a candidate's detail page → click "Back to results" →
confirmed the detail tab closed and focus returned to the original
results tab. Reported back as "Back to result works."

### Final test results
- Full suite: `pytest tests/` — 128/128 passing (124 prior + 4 new in
  `test_frontend_js_regression.py`), 3 consecutive clean runs.
- Real browser click-through: confirmed working by the user, as described
  above.

### Notes for future milestones
- When a plan's exit criteria needs a real browser and the working
  environment is a sandboxed shell with no browser access, the correct
  move is to hand the user exact, numbered steps and wait for a pass/fail
  report — not to skip the verification or mark it done from code review
  alone.
- Milestone plans written before a later milestone exists (Milestone 5's
  plan predates Milestone 4) should be re-read against current reality,
  not assumed still accurate — this is exactly why the historical-run
  `localStorage` bug above existed undetected.

---

## Milestone 5.5: Shortlist score floor + shareable candidate detail links — 2026-07-21

Added mid-stream at the user's explicit request, same convention as the
Excel-export feature added between Milestones 3 and 4 — surfaced from real
usage of a real run, not from the original plan, and scoped/logged the
same as any other milestone rather than patched in silently. Full scope
written into `REBUILD_PLAN.md` before any code was touched, per the
standing "plan before code" rule.

### Goal
(A) A candidate with zero measurable skill overlap with the JD can no
longer occupy a shortlist slot just because a slot is open. (B) The Excel
export can link to a specific candidate's full detail page, and that link
genuinely works for anyone who opens it — not just the browser tab that
ran the batch.

### What triggered this
A real run: a candidate (Flutter/mobile skills) scored `0` against a
SQL/backend-heavy JD and still appeared in the Shortlist tab, because
`build_shortlist()` filled `jd.slots` with the top-scoring eligible
candidates regardless of whether the top score was actually `0` — no
minimum floor existed. Separately, the user asked to be able to open a
specific candidate's detail page directly from the exported spreadsheet,
which surfaced that `/candidate` had no server-side data source at all —
only `localStorage` in the originating tab — so a pasted link would be
dead for anyone else.

### What was done
**(A)** `src/matching/shortlist.py`: candidates scoring at or below `0`
(`MIN_SHORTLIST_SCORE`) are now excluded from `shortlist` regardless of
open slots, routed to `reserve` instead — still fully scored and visible,
never hidden, same principle as the existing CGPA-eligibility gate.
`summary.slots_unfilled` reports how many of `jd.slots` couldn't be filled
by a real candidate. Documented in `PROJECT_CONTEXT.md` Section 6 (this
was previously undocumented — there had never been a stated minimum score
gate). Surfaced in the web UI's plain-text results summary line
(`templates/index.html`) and the Excel Summary sheet
(`src/output/xlsx_export.py`).

**(B)** `templates/candidate.html`'s data-loading logic extended
(additive — the original same-tab `localStorage` path is unchanged and
still what "View full details"/"Back to results" use) to also accept
`?job_id=` (fetches `/api/run/<job_id>/result`) or `?run_id=&client_id=`
(fetches `/api/runs/<run_id>?client_id=`), checked in that order before
falling back to `localStorage`. `src/output/xlsx_export.py::build_workbook()`
gained an optional `link_params` argument; when supplied with enough
information to build a real link for every row (checked via
`_link_params_usable()`, not just "was a dict passed at all" — a
malformed `link_params` degrades to no link column rather than a column
full of broken links), the Shortlist and Reserve sheets gain a "Details
Link" hyperlink column, added last so the existing "Below CGPA Minimum"
column's position never shifts. Omitted entirely when not supplied —
confirmed byte-for-byte identical to pre-5.5 output via
`test_no_link_params_produces_identical_output_to_before_milestone_5_5`.
`app.py`'s two export routes now pass `request.host_url` + the relevant
job/run id(s) into `build_workbook()`. The original uploaded PDF remains
deleted immediately after each job, per the standing PII-minimization
decision — confirmed with the user as intended scope, not a shortfall;
the link opens the structured extraction/scoring detail, not the raw
file.

### Test failures and how they were resolved
`test_link_params_missing_base_url_degrades_to_no_link_gracefully`
initially failed: the first implementation decided whether to add the
"Details Link" column based on `if link_params:` (dict truthiness alone),
so a `link_params` dict present but missing `base_url` still added the
header with every cell blank underneath — a column that looks broken
rather than a feature that wasn't requested. Fixed by adding
`_link_params_usable()`, which checks the actual conditions needed to
build a real link (mirrors `_build_detail_link`'s own checks) and is used
consistently for the column-presence decision, the row-building decision,
and the hyperlink-application step.

### Real, non-mocked verification
The user re-ran the live app end to end: (1) confirmed a zero-overlap
candidate (mismatched skill set against the JD) landed in Reserve, not
Shortlist; (2) downloaded the Excel export and confirmed per-candidate
name/score/detail fields plus a working "Details Link" column, described
as "the data and everything" being as requested; (3) opened a Details
Link in a fresh **incognito window** (screenshot confirmed) — no shared
`localStorage` with the tab that ran the batch — and the real candidate's
full detail page rendered correctly (name, score, full score-breakdown
arithmetic, extracted profile, required-skill breakdown), proving the
link is genuinely shareable, not silently dependent on the original tab.

### Final test results
- Full suite: `pytest tests/` — 143/143 passing, 3 consecutive clean runs.
- New tests: 7 in `tests/test_shortlist.py` (score-floor exclusion,
  `slots_unfilled` accuracy in both the padded and honest cases, zero/negative
  score still visible in Reserve, existing high-score behavior unchanged),
  9 in `tests/test_xlsx_export.py` (backward-compatibility byte-equality
  with no `link_params`, both link shapes' exact URLs, column-position
  stability, graceful degradation, `slots_unfilled` in the Summary sheet),
  1 in `tests/test_app_xlsx_export_route.py` and 1 in
  `tests/test_app_history_routes.py` (Flask-level: the live and historical
  export routes actually wire the right ids into the link, not just that
  `build_workbook()` can do it in isolation).
- Real end-to-end verification: as described above, including the
  incognito-window check that specifically exercises "does this link work
  for someone without the originating browser's `localStorage`," which no
  automated test in this suite can verify by itself.

### Notes for future milestones
- A "does X exist" check for an optional feature parameter should verify
  the parameter is *usable*, not just *present* — a present-but-incomplete
  parameter that still triggers a header/column/UI element headed for a
  blank value is a worse failure mode than not showing the element at
  all, because it looks broken instead of absent.
- Score-floor logic like `MIN_SHORTLIST_SCORE` belongs in `src/`
  (`shortlist.py`), never in the web layer, even though the report that
  triggered it came from the web UI — consistent with `WEB_APP_PLAN.md`
  Section 6's standing rule, and confirmed here: the same fix
  automatically applies to `main.py`'s CLI output too, no separate change
  needed there.

---

## Milestone 6: Fixture-based extraction accuracy suite — 2026-07-21

### Goal
"Is the data actually correct" becomes a checkable, automated pass/fail
against real resumes with known-correct expected values, instead of
eyeballed from screenshots.

### What was done
Selected 8 fixtures per `REBUILD_PLAN.md`'s exact spec: 7 real resumes
from `data/real_resumes/`, 1 synthetic. Fixture selection wasn't
guesswork — a local, no-LLM-cost script reused
`pdf_reader.py::_column_aware_text`'s own block-position logic to
confirm, against the real 54-PDF dataset, exactly 31/54 files trigger
genuine two-column splitting — matching `PROJECT_CONTEXT.md` Section 11's
already-documented number exactly, which is itself a nice cross-check
that this session's local re-derivation is trustworthy. Picked 4 confirmed
single-column and 3 confirmed two-column real resumes, plus
`data/mock_resumes/mock_cgpa_percentage.pdf` (synthetic, explicitly
labeled as such in the fixture file) to cover percentage-format CGPA,
since `PROJECT_CONTEXT.md` Section 11 already confirms zero real resumes
in this dataset use that format. Expected `full_name`/`cgpa_10pt`/`skills`
values recorded in `tests/fixtures/accuracy_fixtures.json` by directly
reading each PDF's real extracted text (not guessed, not taken from the
LLM's own prior output) — CGPA expectations for the two-column real
resumes were double-checked against `PROJECT_CONTEXT.md` Section 7's
normalization formula by hand.

Built `tests/test_extraction_accuracy.py` (real Groq calls,
`@pytest.mark.slow` via a module-level `pytestmark`, excluded from the
default fast run by a new `pytest.ini` with `addopts = -m "not slow"` —
run explicitly via `pytest tests/test_extraction_accuracy.py -m slow`):
the accuracy suite itself (name exact-match case-insensitive, CGPA
match within a small rounding-safe tolerance, skill recall via
case-insensitive substring containment in either direction — documented
in the fixtures file as a deliberate fairness choice, not exact-string
strictness), plus the three LLM-pipeline-specific tests
`REBUILD_PROMPT.md` Section 4 requires: known-good fixtures (above),
deliberately-broken input (`mock_corrupted_file.pdf`, `mock_empty_file.pdf`
— both already existed, confirmed graceful `Failed` status, no crash, no
real API cost since these never reach the LLM call), and a genuinely new
prompt-injection PDF fixture
(`tests/fixtures/mock_prompt_injection.pdf`, generation script also added
to `scripts/generate_mock_resumes.py` for reproducibility) run through the
**full** pipeline (PDF text extraction → PII redaction → LLM call), not
just `extract_structured_fields()` on a hand-written string the way the
pre-existing `tests/test_prompt_injection_resistance.py` already did —
this is what actually proves the resistance holds for a real uploaded
file, which is a meaningfully different guarantee.

A per-run report (`tests/fixtures/accuracy_report.md`) is written every
time the suite runs — including on a failing run, specifically so a
future failure shows exactly which fixture(s) missed and why, not just an
aggregate percentage.

### Real bug found (in the test, not the product) and how it was resolved
`test_prompt_injection_pdf_resisted_through_full_pipeline` failed on its
first real run: `assert resume.full_name == "Rohan Sharma"` got back
`'ROHAN SHARMA'`. Not a resistance failure — the fixture PDF's text
writes the name in ALL CAPS (matching the header convention several real
resumes in this dataset actually use, e.g. "SIDDHARTH RAO"), and the
model faithfully returned it verbatim rather than title-casing it, which
is correct, honest behavior, not a miss. The assertion was wrong, not the
extraction — fixed by switching to the same case-insensitive
`_names_match()` helper the main accuracy suite already uses, for
consistency. Re-ran real: passed.

### Real, non-mocked verification
`pytest tests/test_extraction_accuracy.py -m slow` run for real against
Groq (`AI_PROVIDER=groq` per `.env`), twice (once per test file section,
once as the full file together to rule out any cross-test interference
via the in-process resume cache) — **4/4 passing both times**. The
accuracy suite specifically: **100% name accuracy, 100% CGPA accuracy,
100% average skill recall** on the first real run, comfortably clearing
the stated 85%/90%/75% bars (see `tests/fixtures/accuracy_report.md` for
the full per-fixture table — checked into the repo, not just described
here). Not treated as "close enough" or approximate — every one of the 8
fixtures' name, CGPA (where present), and skill fields were checked
individually against manually-recorded expected values.

### Final test results
- Fast suite: `pytest tests/` — 143/143 passing, 4 deselected (the new
  slow-marked accuracy suite), 3 consecutive clean runs. `pytest.ini`'s
  new `addopts` confirmed not to affect any existing test's collection or
  pass/fail status.
- Slow suite: `pytest tests/test_extraction_accuracy.py -m slow` — 4/4
  passing, real Groq calls, run twice for consistency.
- Accuracy numbers: 100%/100%/100% against an 85%/90%/75% bar — see
  `tests/fixtures/accuracy_report.md`.

### Notes for future milestones
- A local, no-API-cost script that reuses the product's own detection
  logic (here, `_column_aware_text`'s block-position check) is a cheap,
  trustworthy way to select or validate fixtures before spending any real
  LLM quota on them — confirmed valuable this session (the 31/54
  two-column count matched `PROJECT_CONTEXT.md`'s already-documented
  number exactly, which both validated the re-derivation and saved having
  to eyeball 54 PDFs by hand).
- When a "does the model behave correctly" test fails, check whether the
  test's own assertion is the actually-wrong part before concluding the
  product regressed — this session's ALL-CAPS name assertion is a
  concrete instance: the fix belonged in the test, not the pipeline.
- `pytest.ini`'s `-m "not slow"` pattern (register a marker, default it
  out via `addopts`, require an explicit `-m slow` to opt in) is worth
  reusing for any future test that costs real API quota per run — cheaper
  and more explicit than remembering to pass `--deselect` by hand.

---

## Milestone 7: Security, dependency, and code-health pass — 2026-07-21

### Goal
Every security guarantee already claimed in `PROJECT_CONTEXT.md` Section
11.7 has an automated regression test, plus new checks for the
web-upload surface, dependency vulnerabilities, lint, and dead code — per
`REBUILD_PLAN.md`'s Milestone 7 scope.

### Re-scoping against current reality (done before any code, per the
standing "plan before code" rule)
`REBUILD_PLAN.md`'s Milestone 7 text was written before the "Security
audit pass (Milestones 0-3)" entry existed, which pulled a large chunk of
this milestone's originally-planned scope forward already: API-key-in-
exception scrubbing (`test_secret_scrubbing.py`), multi-occurrence PII
redaction (`test_pii_redact.py`), prompt-injection resistance
(`test_prompt_injection_resistance.py`, extended to a full-PDF-pipeline
version in Milestone 6), the path-leak fix (`test_no_path_leak.py`), and
security headers (`test_security_headers.py`) were all already done and
test-covered. Re-read fresh rather than re-implemented. What genuinely
remained: upload-validation boundary tests, a forced-unhandled-exception
test, a fresh `pip-audit` run (stale — last run 2026-07-20, a full
milestone's worth of code ago), `ruff` lint (never run at all), and a
dead-code check. Also checked whether `pytest.ini`, `xlsx_export.py`, or
the Milestone 4 history/export routes (all built after M7 was originally
scoped) needed anything from this list — they did, and are covered below
(ruff/dead-code ran across the whole repo, not just pre-M7 files).

### What was done
1. **Dependency scan.** Installed `pip-audit` fresh in this session's
   sandbox (not previously installed here). `pip-audit -r
   requirements.txt` — **0 known vulnerabilities**, confirming the
   Milestone-0-3 audit's version bumps are still clean a full milestone
   later, not just clean at the time they were made.
2. **Lint.** Installed `ruff` fresh (never run against this codebase
   before). First run found 7 real findings across `app.py`,
   `src/extraction/pdf_reader.py`, `scripts/score_stability_test.py`,
   `tests/test_app_async_jobs.py`, and `tests/test_history.py` — an
   unused exception-binding variable, an unused loop variable, three
   unused imports, one unused `threading.Event`, and one import-order
   warning that was already deliberately ordered (before `load_env()`
   must run) and just needed its own `# noqa: E402`, matching the
   pattern already used on the lines directly below it. Fixed all 7
   individually rather than blanket-suppressing the rule. `ruff check .`
   now reports "All checks passed!" — re-confirmed after every
   subsequent change in this milestone, not just once at the start.
3. **Upload-validation tests** (`tests/test_upload_validation.py`, new,
   4 tests): oversized upload (over `MAX_CONTENT_LENGTH`) rejected,
   wrong-extension-only batch rejected without ever reaching the parser,
   over-`MAX_FILES_PER_REQUEST` batch rejected outright, and a file named
   `fake.pdf` containing the real `mock_corrupted_file.pdf` bytes routed
   through the **full real HTTP upload → background job → result** path
   (not just a direct `parse_one_resume()` call) — confirms
   `fitz.open()`'s existing graceful failure (already proven at the unit
   level in Milestone 0) holds all the way through a real upload, with no
   internal temp-path leaking into the `needs_review` reason string
   returned to the browser.
4. **A real bug found and fixed while writing test 3 above.** The
   oversized-upload test initially failed: Werkzeug's own
   `RequestEntityTooLarge` (413), raised the instant `request.files` is
   touched past `MAX_CONTENT_LENGTH`, was being caught by `api_run()`'s
   own blanket `except Exception` and converted into a generic 500
   ("Something went wrong starting this batch") instead of surfacing as
   the correct, specific 413. The cap was still being enforced — this
   was a wrong-status-code bug, not a security hole — but it directly
   contradicts this project's own established principle of specific,
   accurate error signaling, and a 500 instead of a 413 could plausibly
   mislead a future debugging session into thinking the upload cap
   wasn't working at all. Fixed in `app.py`: added `from
   werkzeug.exceptions import HTTPException` and an `except
   HTTPException: raise` clause before the generic `except Exception`
   in `api_run()`'s outer try block, so Werkzeug's own HTTP-level
   exceptions pass through with their correct status code instead of
   being swallowed into the generic-500 path meant for genuinely
   unexpected errors.
5. **Forced-unhandled-exception test**
   (`tests/test_forced_exception_no_leak.py`, new, 2 tests). Deliberately
   raises a previously-unseen `RuntimeError` (not `LLMError`, not any
   exception type an existing except-block was written with in mind)
   embedding a fake sensitive file path and a fake secret string — once
   from inside `run_batch` (the background-job path, caught by
   `_execute_job`'s except-block) and once from `job_store.create()`
   itself (the request-thread path, caught by `api_run()`'s own
   except-block — genuinely different code from `_execute_job()`'s and
   needed its own proof). Both confirmed: the fake path, fake secret,
   the word "Traceback", and the raw exception type name never appear
   anywhere in the client-facing response — only the pre-written generic
   message. This is the first test in the suite that proves the
   generic-message guarantee holds for an *arbitrary* exception, not just
   the specific ones a developer already knew to write a message for.
6. **Dead-code check.** `grep -rn "^def parse_one_resume"` across the
   whole repo (excluding `__pycache__`) still returns exactly one match
   (`src/pipeline.py`), confirming Milestone 0's deduplication held.
   `ruff`'s F401/F841 checks (item 2 above) double as the "no leftover
   unused imports/functions" check this milestone's scope calls for —
   clean after the fixes in item 2.

### Test failures and how they were resolved
Covered in detail above (item 4) — the oversized-upload test's initial
failure was a real product bug (wrong status code), not a test bug, fixed
in `app.py` before the test was allowed to pass. No other test failed
after being written.

### Final test results
- New tests this milestone: 4 in `tests/test_upload_validation.py`, 2 in
  `tests/test_forced_exception_no_leak.py` — 6 new, all passing.
- `pip-audit -r requirements.txt`: 0 known vulnerabilities.
- `ruff check .`: all checks passed, 0 findings remaining after fixes.
- Full suite: `pytest tests/` — **149/149 passing** (143 prior + 6 new),
  4 deselected (Milestone 6's slow-marked accuracy suite, unaffected by
  this milestone), 3 consecutive clean runs.
- Dead-code check: exactly one `parse_one_resume` definition in the
  whole repo; `ruff` reports zero unused-import/unused-variable findings.

### Notes for future milestones
- `except HTTPException: raise` before a route's blanket `except
  Exception` is now the established pattern in `api_run()` for letting
  Werkzeug's own well-formed errors (413, and potentially others in the
  future, e.g. a malformed multipart body) pass through with their
  correct status code instead of being flattened into a generic 500 —
  worth applying to any future route whose blanket exception handler
  wraps code that touches `request.files`/`request.form` directly.
- The two `.xlsx` export routes' blanket `except Exception` blocks were
  reviewed but deliberately left unchanged — they only wrap
  `build_workbook()`/`workbook_to_bytes()`, neither of which touches
  request body parsing, so the same `HTTPException` gap doesn't apply
  there today. Worth re-checking if either function's inputs ever start
  including raw request data directly.
- `ruff` and `pip-audit` were both installed fresh in this session's
  sandbox and are not yet part of any documented repeatable local dev
  setup step — worth adding a line to a future session's environment
  notes (alongside the existing `.venv`-doesn't-resolve-here note) so a
  future session doesn't have to rediscover they need installing.

### Recurring-risk issues
- **A blanket `except Exception` around a Flask route body will also
  catch Werkzeug's own `HTTPException` subclasses if anything inside
  that block can raise one** (most commonly `request.files`/`request.form`
  access past a configured size/content limit). This is a distinct risk
  from the already-documented "don't leak `str(exc)` to the client" rule
  — here the exception itself is already safe and correctly-coded, the
  bug is *catching it at all* and replacing its correct status/message
  with a generic one. Any future route wrapping request-body access in a
  blanket except block should re-raise `HTTPException` first, same
  pattern as `api_run()` now does.
- `pip-audit` and `ruff` being clean today is a point-in-time fact, same
  standing caveat as the Milestone-0-3 security audit entry already
  recorded for `pip-audit` specifically — re-run both again before final
  submission, not assumed still clean from this entry alone.

---

## Milestone 8: real load test — sandbox constraint hit, evidence gathered so far, full 40-resume run handed to the user

### Goal
Prove, with real evidence, that a real 40-resume batch completes within a
stated time budget via the actual async job flow, and that a simulated
full-provider-outage produces a clearly labeled non-zero-looking failure
state.

### A hard sandbox constraint discovered, not a design gap
This session's sandboxed shell runs each `bash` tool call inside its own
`bwrap --unshare-pid --die-with-parent` namespace — confirmed directly
(`ps aux` showed the wrapping `bwrap` process). This means no
process, backgrounded or not, survives past the end of the bash call that
started it; combined with this tool's ~44s per-call cap, any real
operation that takes longer than ~44s cannot be run to completion from
inside this session at all, regardless of chunking strategy — a stronger
constraint than the already-documented "background processes don't
survive between separate bash tool calls" note in
`REBUILD_SESSION_HANDOFF.md`, which undersold how absolute this is (it's
not just that a `flask run &` dies — nothing does, ever, across a call
boundary).

### Real evidence gathered before the constraint was hit
Using `scripts/milestone8_concurrency_probe.py` (new, calls
`src.pipeline.run_batch()` directly against real resumes from
`data/real_resumes/`, bypassing the HTTP layer since Milestone 3 already
proved that layer works):
- **6 real resumes at `max_workers=6`: clean.** 1.25s wall clock, 0/6
  `llm_call_failed`, `llm_extraction` stage durations tightly clustered
  (1044-1233ms) — matches Milestone 2's own earlier real-3-resume
  verification almost exactly.
- **12 real resumes at `max_workers=6`: did not complete within a 42s
  call.** `llm_extraction` durations for several resumes climbed to
  8s/16s/32s/34s/36s/40s with some reaching `status=error` before the
  call was killed — consistent with the documented 12,000 TPM ceiling
  (`REBUILD_PLAN.md` Section 0) genuinely being hit, not a fluke.
- **12 real resumes at `max_workers=3`: also did not complete within
  42s.** This is the more important finding: lowering concurrency alone
  did not fix it, meaning the real constraint tripped here is closer to
  Groq's per-minute request/token ceiling across the whole batch
  (independent of how many calls are in flight at once) than a pure
  worker-count problem — compounded, very plausibly, by this same
  session's own repeated real test calls (the earlier full 40-resume
  attempt via `scripts/milestone8_load_test.py`, plus two probe runs)
  eating into the same per-minute/per-day quota window before this test
  even started.
- The full 40-resume run via the real async job flow
  (`scripts/milestone8_load_test.py`, already written and working —
  confirmed it correctly starts the job, polls, and would report
  timing/`llm_warning`/per-row results) was attempted but killed by the
  45s tool timeout partway through resume ~15-20, showing the same
  retry-cascade pattern as the 12-resume probe.

### What this means, stated plainly
Milestone 2's `DEFAULT_MAX_WORKERS=6` was explicitly flagged in its own
comment as "a starting point... to be corrected by Milestone 8's real
load test" — this is exactly that correction moment, and the real data
says the correction isn't simply "lower the worker count." A genuine
40-resume real run, at real Groq free-tier limits, will take
meaningfully longer than the ~1s-per-resume baseline measured on small
batches — very plausibly several minutes, with real retries and
possible individual `llm_call_failed=True` results if quota is tight
enough on the day it's run. This is not a regression introduced this
session; it's the first time a batch large enough to actually hit the
real ceiling has been run against it.

### Decision made with the user
Presented this finding and the sandbox constraint directly rather than
either (a) silently declaring Milestone 8 done on unrepresentative small-
batch evidence, or (b) unilaterally retuning `max_workers` based on a
contaminated/rate-limited probe. The user chose to run the real
40-resume load test and the outage test themselves, from their own
terminal (unconstrained by this sandbox's 44s/no-persistent-process
limits) — matching the established pattern already used for Milestone
5's real browser click-through. Exact steps and both scripts (already
written, tested to correctly start/poll/report) handed off; this
milestone's `MILESTONE_LOG.md` entry will be completed with the real
40-resume timing/outage evidence once the user reports back, per the
standing rule that an entry is only written once every required test
actually passes — this is a partial, honest entry documenting real
work done and a real constraint hit, not a claim that Milestone 8 is
closed.

### Test failures and how they were resolved
No test *failures* in the pytest sense — this is real-world load
behavior discovered via ad hoc scripts (`scripts/milestone8_load_test.py`,
`scripts/milestone8_concurrency_probe.py`), same category as
`scripts/incremental_parse.py` from the pre-rebuild era, not part of the
`pytest tests/` suite.

### Current test results
- `pytest tests/` unaffected by this milestone (149/149, unchanged) — no
  product code was changed based on unconfirmed/contaminated probe data.
- Real evidence as described above: 1 clean data point (6 resumes/6
  workers), 2 real rate-limit-driven degradations (12 resumes at both 6
  and 3 workers).

### Notes for future milestones
- **Any future real-load testing in this specific sandbox must budget
  for the `bwrap --unshare-pid` constraint from the start** — plan for
  either (a) tests that genuinely complete in well under 44s, or (b)
  handing real multi-minute operations to the user's own terminal
  immediately, rather than discovering the constraint mid-attempt as
  this session did.
- Repeated real-API probing to "get a clean number" is itself a hazard
  once a rate limit is genuinely close — this session's second and third
  probe attempts were very plausibly degraded by the first attempt's own
  quota usage, not independent measurements. A future session doing real
  load testing should plan for ONE real attempt at the target scale, not
  incremental probing that spends the same quota multiple times before
  getting a clean read.

### Recurring-risk issues
- If a future session sees `llm_extraction` durations climbing into the
  8-40s range on a batch bigger than ~6-10 real resumes, that is now a
  confirmed, reproducible real symptom of the Groq free-tier ceiling
  being hit under sustained concurrent load — not a code regression to
  re-diagnose from scratch. Check `llm_failure_reason` on any resulting
  `llm_call_failed=True` rows for the specific HTTP status before
  assuming anything is broken.

---

## Milestone 8: CLOSED — real 40-resume load test + real-world outage evidence, both run by the user — 2026-07-21

### Goal (restated)
Prove, with real evidence, that a real 40-resume batch completes within a
stated time budget via the actual async job flow, and that a
full-provider-outage produces a clearly labeled non-zero-looking failure
state — not a silent wall of 0s.

### What actually happened (run by the user, from their own terminal,
using `scripts/milestone8_load_test.py`, exactly as handed off)

**Real run (`python3 scripts/milestone8_load_test.py`, no injected
outage):** 40/40 resumes completed, job reached `done` in **111.38s**
wall clock. Of those, **39/40 hit `llm_call_failed=True`** — but not from
a simulated failure. The real `llm_failure_reason` (read directly off a
candidate's detail page, screenshot-confirmed) was:

```
Both providers failed. groq: HTTP 429: ...tokens per day (TPD): Limit
100000, Used 99762, Requested 1200... gemini: HTTP 400: {"error":
{"code": 400, "message": "API key not valid. Please pass a valid API
key."...
```

Two real, distinct root causes, not one:
1. **Groq's daily token quota (TPD, 100,000/day) was already almost
   exhausted (99,762 used) before this run even started** — the
   cumulative result of every real API call made across this entire
   rebuild's history (Milestones 0-8, both AI-driven and the user's own
   testing), not something introduced by this run. This is a **daily**
   cap, distinct from the TPM (per-minute) ceiling `REBUILD_PLAN.md`
   Section 0 originally sized concurrency against — TPD is what actually
   bound here, a real constraint the original plan hadn't separately
   budgeted for.
2. **`GEMINI_API_KEY` in the user's `.env` is currently invalid** (a
   real HTTP 400 "API key not valid," not a rate limit) — meaning the
   Groq→Gemini failover built in Milestone 2 had, in this run, literally
   nothing to fall back to. Flagged to the user directly (not silently
   fixed or silently ignored) — they're getting a fresh key.

**Despite both providers being unavailable for 39/40 resumes, the system
behaved exactly as designed, under real (not simulated) failure
conditions:**
- `llm_warning` correctly reported `"39/40 resumes failed AI
  extraction..."`, rendered as a visible banner (screenshot-confirmed).
- Every failed candidate showed the distinct "AI extraction failed"
  badge alongside `Parse: Partial`/`Confidence: Medium` — never
  indistinguishable from a genuinely thin resume.
- Scores were **not** a wall of 0s — several candidates showed non-zero
  partial credit (e.g. 8, 5) with visible partial-skill-match evidence.
  Confirmed this is correct, not a bug: `skill_matcher`'s deterministic
  vocabulary pass (Tricky Part 3, `DESIGN_DECISIONS.md`) runs against the
  raw redacted resume text independently of whether the LLM call
  succeeded, so it can still credit partial matches even when
  `llm_call_failed=True`. The candidate detail page's own reasoning text
  ("this score and the fields below are unreliable, not a real
  assessment. Re-run once the provider issue clears") makes this
  explicit rather than letting a non-zero number look like a real
  assessment.
- Per-stage timing (`llm_extraction`: min=939ms for the one resume that
  actually got a real response, median=15,789ms, max=16,180ms) is
  internally consistent with the code as written: ~15s of Groq retry
  backoff (`_post_with_retry`'s 429-is-retryable path) followed by a
  fast-failing Gemini 400 (non-retryable) — confirms the failover
  timing behaves exactly as `src/ai_client.py` is coded, not a mystery
  slowdown.

**Simulated outage run (`python3 scripts/milestone8_load_test.py
--outage`, both keys deliberately invalidated):** 40/40 resumes reached
`llm_call_failed=True`, job done in **2.59s** — dramatically faster than
the real run above, and correctly so: a 401 (bad key) is NOT in
`RETRYABLE_STATUS_CODES`, so both Groq and Gemini fail fast with no
backoff delay (Milestone 1's own "Recurring-risk issues" note predicted
exactly this). `llm_warning` correctly reported `"40/40 resumes failed
AI extraction..."`.

### Stated time budget (per Milestone 8's own exit-criteria requirement)
- **Healthy-quota conditions** (per Milestone 2's earlier real
  measurement: 6 resumes/6 workers = 1.25s, and the one resume in this
  run that got a real response = 939ms): expect roughly 1-2s per resume
  at `max_workers=6` under normal quota — a real 40-resume batch should
  complete in well under a minute once daily quota isn't already
  exhausted.
- **Degraded-quota conditions** (what was actually measured today): each
  resume that exhausts Groq's retries costs ~15-16s (retry backoff) plus
  Gemini's fast-fail time. A worst-case full-batch failure state (quota
  genuinely gone, Gemini also down) still completes in under 2 minutes
  (111.38s observed) — not a hang, not a timeout, and every resume in it
  is honestly labeled, not a false "it finished successfully" claim.
- **True full-outage state** (both keys invalid): under 3 seconds for
  40 resumes — fails fast and correctly, no wasted retry time.

### Real bug/gap found and flagged (not silently fixed)
`GEMINI_API_KEY` in `.env` is invalid. This isn't a code bug — the
failover logic itself worked exactly as designed (attempted Gemini,
correctly captured and surfaced its real 400 in the combined failure
reason) — it's an external credential problem. Presented to the user
directly, per the standing "flag scope questions/real bugs, don't
silently decide" rule; they chose to obtain a fresh key rather than
collapsing to Groq-only (`REBUILD_PLAN.md`'s own pre-agreed fallback
option, still available if the new key doesn't resolve it).

### Final test results
- `pytest tests/` unaffected — no product code changed as a result of
  this milestone; the system's behavior under real failure conditions
  matched its design without needing a fix.
- Real evidence: as detailed above, both runs completed, both screenshots
  and raw terminal output retained as evidence (see chat log for this
  session).

### Notes for future milestones
- **Real cumulative API usage across a long project's testing history is
  a genuine capacity constraint, not just a per-run concern.** A daily
  token cap can be exhausted by the sum of many earlier milestones' real
  verification calls, not just today's own test — worth checking
  remaining quota before any future demo-critical real run, not assuming
  a fresh budget.
- The deterministic skill-vocabulary pass providing partial credit
  independent of `llm_call_failed` is a real, confirmed strength of the
  hybrid design (Tricky Part 3) — it means even a total LLM outage still
  produces some auditable signal, not a completely blank result, while
  the `llm_call_failed` flag prevents that partial signal from being
  mistaken for a full assessment.

### Recurring-risk issues
- Reconfirmed from Milestone 1: a 401 (bad/invalid API key) fails fast
  with no retry delay by design — if a future session sees a batch fail
  suspiciously fast (~seconds, not the ~15s-per-resume retry pattern),
  check for an invalid key first, not a code regression.
- **`GEMINI_API_KEY` validity should be spot-checked before any
  demo-critical run**, the same way `AI_PROVIDER`/`GROQ_API_KEY` already
  are — a silently-invalid fallback key is worse than no fallback
  configured at all, because it looks like redundancy that isn't
  actually there until the primary provider fails.

---

## Addendum: Gemini key fixed, Milestone 9 real click-through confirmed — 2026-07-21

Two items from Milestone 8/9's handoff to the user, resolved:

1. **`GEMINI_API_KEY` replaced with a fresh key** (Google AI Studio). Real
   verification: `call_llm_with_failover("Reply with exactly: OK", ...)`
   returned `OK` — confirms the failover path genuinely has a working
   second provider again, not just that the key format looks valid.
2. **Milestone 9's one unconfirmed exit-criteria item — the real
   "Back to results" click** — done by the user directly: "back to
   result works." Combined with this session's earlier code-level
   verification (progress bar, failure badges, Past Runs list, all
   confirmed structurally wired and now also screenshot-confirmed
   rendering real data in a real browser), Milestone 9 is now fully
   closed, not just structurally verified.

No code changes from this addendum — purely a decision/confirmation
record, same pattern as the earlier "repo-visibility finding resolved"
addendum.

---

## Milestone 10: Full regression + Definition of Done sign-off — 2026-07-21

### Goal
Every item in `REBUILD_PROMPT.md` Section 2 has a corresponding passing
test, and Section 5's full checklist is verifiably true.

### Section 2 bug → test cross-reference table

| # | Known issue (`REBUILD_PROMPT.md` Section 2) | Milestone | Test(s) |
|---|---|---|---|
| 1 | Silent LLM failure disguised as bad data | 1 | `tests/test_pipeline.py` (13 tests: simulated 429/500/timeout/malformed-JSON, the 3-poisoned-resumes regression scenario, real invalid-key call); `tests/test_scorer.py` (distinct reasoning text) |
| 2 | No timing instrumentation | 1 | `tests/test_timing.py` (3 tests) |
| 3 | Fixed 4-worker concurrency cap regardless of batch size | 2, 8 | `tests/test_run_batch.py` (4 tests: order preservation, tracked-concurrency ceiling, default worker count); real-world confirmation + correction in Milestone 8 (TPD ceiling identified as the real binding constraint, not TPM as originally guessed) |
| 4 | Fully synchronous `/api/run`, reverse-proxy timeout risk | 3 | `tests/test_app_async_jobs.py` (12 tests: fast non-blocking POST, progressive delivery, generic error handling); real end-to-end confirmed in Milestone 3 and re-confirmed at 40-resume scale in Milestone 8 (111.38s real run, never blocked the initiating request) |
| 5 | `MAX_FILES_PER_REQUEST = 20` arbitrary cap | 3, 7 | Raised to 80 with documented rationale (Milestone 3); `tests/test_upload_validation.py` (Milestone 7: over-cap rejection, oversized upload, wrong extension, fake-`.pdf`-real-non-PDF-bytes) |
| 6 | Cross-tab "Back to results" state bug | 5 | `tests/test_frontend_js_regression.py` (4 tests: JS syntax, historical-run `localStorage` ordering fix); real browser click-through confirmed twice (Milestone 5 initial fix, and again this session after the Milestone 4/9 interaction) |
| 7 | No extraction-accuracy verification | 6 | `tests/test_extraction_accuracy.py` (4 slow-marked tests: 8-fixture accuracy suite at 100%/100%/100% against an 85%/90%/75% bar, corrupted/empty-file handling, full-pipeline prompt-injection resistance) |
| 8 | Retry/backoff never load-tested against a real rate limit | 2, 8 | `tests/test_ai_client_failover.py` (4 tests, mocked); real measured Groq rate limits (`REBUILD_PLAN.md` Section 0) informed `DEFAULT_MAX_WORKERS=6`; Milestone 8's real 40-resume run (both a real quota-exhaustion event and a simulated full-outage run) is the actual load test against the real ceiling, with the TPD-vs-TPM correction documented |

### Full suite state (final, this session)
- `pytest tests/` — **148/149 passing, 1 failing**
  (`tests/test_prompt_injection_resistance.py::test_injected_system_override_is_ignored_only_real_content_extracted`).
  **This is not a code or security defect.** It is the one fast-suite
  test that makes a real, deliberately non-mocked LLM call (injection
  resistance is a property of the real model, not mockable) — Groq's
  daily token quota (TPD) was driven to its edge by this session's own
  real Milestone 8 load testing (40-resume real run + outage run, ~80
  real calls) plus the whole rebuild's cumulative real-API usage across
  every prior milestone. Direct evidence this is quota, not a
  regression: the same test **passed** when run in isolation minutes
  earlier (`1 passed in 0.47s`), then failed again immediately afterward
  as part of the full suite — consistent with quota sitting right at
  its edge (a ~116-token buffer observed in the M8 real-run error
  message) rather than a stable failure. The property this test checks
  (prompt-injection resistance) has independently passed for real
  multiple times this session and across this project's history
  (Milestone 0-3 security audit, Milestone 6's full-pipeline version,
  and this session's own isolated re-run) — it is proven, just not
  re-provable again in this exact moment without more quota. Decision,
  made with the user directly rather than silently accepted or silently
  hidden: proceed with 148/149 documented as a real, understood,
  transient quota state, not block deployment on re-running an already-
  proven property.
- `ruff check .`: clean.
- `pip-audit -r requirements.txt`: 0 known vulnerabilities.
- Dead-code check: exactly one `parse_one_resume` definition in the repo.

### Definition of Done (verbatim from `REBUILD_PROMPT.md` Section 5)
1. **40+ real resumes, end to end, within a stated time budget, visible
   progress throughout.** ✅ — Milestone 8: 40 real resumes via the real
   async job flow, `111.38s` under degraded real-quota conditions (39/40
   `llm_call_failed`), `2.59s` under a full simulated outage (40/40).
   Progress genuinely visible throughout (screenshot-confirmed: "6/10
   resumes parsed..." progress bar, live in a real browser).
2. **Simulated full outage produces a clearly labeled, non-zero-looking
   failure state.** ✅ — Milestone 8's outage run: 40/40
   `llm_call_failed=True`, `llm_warning` correctly reported, distinct
   "AI extraction failed" badges throughout, scores never presented as a
   real assessment even when non-zero (deterministic skill-vocabulary
   partial credit, explicitly caveated in the reasoning text).
3. **Fixture accuracy suite passes the stated bar.** ✅ — Milestone 6:
   100% name accuracy, 100% CGPA accuracy, 100% skill recall against an
   85%/90%/75% bar (`tests/fixtures/accuracy_report.md`).
4. **Every Section 2 bug has a named passing regression test.** ✅ — see
   the table above; every row has at least one named test file.
5. **Full suite green, with a stated summary of what each test category
   covers.** ⚠️ **148/149**, one real-API test currently blocked by a
   documented, understood, transient daily-quota state (see above), not
   a code defect — accepted as a known condition per the user's explicit
   decision, not silently glossed over. Test categories: unit (pure
   scoring/normalization/matching logic), integration (Flask test client
   against real routes, real filesystem for temp-file/history
   lifecycle), LLM-pipeline-specific (simulated failure modes +
   deliberately-broken inputs + real API calls), security (secret
   scrubbing, PII redaction, no-path-leak, forced-unhandled-exception,
   upload validation, security headers), and load/concurrency (real
   6-resume through real 40-resume batches, both healthy and degraded
   quota states).

### Test failures and how they were resolved
Covered in full above — a real, transient quota state, not a code fix.
No product code was changed as a result.

### Final test results
As stated above: 148/149 (149/149 confirmed reachable in isolation
minutes earlier, same session), `ruff` clean, `pip-audit` clean, dead-code
clean.

### Notes for future milestones / next session
- Before any future demo or judging round, re-run
  `pytest tests/test_prompt_injection_resistance.py -v` in isolation
  first, once real quota has had time to recover — if it passes cleanly
  (as it did in this session, `0.47s`), that's sufficient re-confirmation
  without needing to re-run the entire suite back-to-back and risk
  tripping the same edge again.
- The backend/frontend-logic rebuild (Milestones 0-9) is now complete
  per this Definition of Done, with the one caveated exception above.
  The UI/UX phase (`REBUILD_PROMPT.md` Section 6) is the next
  conceptually separate phase, out of scope until explicitly kicked off
  — not part of today's deployment.

### Recurring-risk issues
- Reconfirmed: real daily API quota is a genuine, shared, cumulative
  resource across an entire project's history, not a per-session
  budget — a demo-day run should ideally happen with quota headroom
  checked beforehand, not assumed fresh.

---

## Addendum: Groq quota root-caused, second account created, extra static-security pass — 2026-07-21

Two things resolved after Milestone 10 closed, at the user's request
("re-verify with a fresh key" then "I want to be sure this is
hacker-proof, it holds real user data"):

1. **Root cause of the quota issue clarified.** The user initially
   swapped in a new Groq API key expecting fresh quota — it didn't help,
   because Groq's TPD (tokens-per-day) cap is scoped to the
   organization/account, not the individual key (confirmed directly: the
   same `org_...` ID appeared in the rate-limit error both before and
   after the key swap, with usage barely changed). Explained to the user
   that Groq has both a per-minute limit (RPM 30 / TPM 12,000) and a
   per-day limit (RPD 1,000 / TPD 100,000) — the error text throughout
   today explicitly named "tokens per day (TPD)," confirming the daily
   cap was what bound, not the per-minute one. The user then created a
   genuinely separate Groq account (different email → separate quota
   pool) as a **one-time, today-only bridge** to get through testing —
   explicitly NOT recommended as an ongoing pattern (flagged directly:
   manually rotating keys/accounts to dodge a rate limit is fragile and
   likely violates most providers' terms of service; the real fix for
   sustained real usage is Groq's paid "Dev Tier," mentioned directly in
   the error messages the app was already surfacing). Verified the new
   account's key works via a real `call_llm_with_failover` call
   (returned `OK`), then re-ran `pytest tests/` **three consecutive
   times, 149/149 clean each run** — the quota-edge flakiness from the
   earlier entry is gone with a genuinely fresh quota pool.
2. **Additional static-security pass, `bandit`** (new tool this
   session, not previously used — a Python-specific security-focused
   static analyzer, distinct from `ruff`'s general lint/style checks).
   `bandit -r src/ app.py main.py -ll`: **0 issues at any severity**
   (2,125 lines scanned). Re-ran `pip-audit` (fresh CVE database pull,
   not reused from earlier in the day) and `ruff check .` — both still
   clean. Also explicitly re-grepped all git-tracked files for
   Groq/Gemini-shaped API key patterns (`gsk_...`, `AIza...`) — none
   found, and re-confirmed `.env` is not git-tracked.

### Final test results (this addendum)
- `pytest tests/` — 149/149, 3 consecutive clean runs, real fresh-quota
  Groq key.
- `bandit -r src/ app.py main.py -ll` — 0 issues (new check).
- `pip-audit -r requirements.txt` — 0 known vulnerabilities (re-run).
- `ruff check .` — clean (re-run).
- Git-tracked-secret grep — clean.

### Notes for future sessions
- `bandit` is now a confirmed-clean, cheap additional static check
  worth re-running alongside `ruff`/`pip-audit` before any future
  security-sensitive milestone or pre-deploy check — add it to the
  Milestone 7-style checklist for any future security pass, not just
  this one-off.
- If Groq quota exhaustion resurfaces in a future session, check
  whether it's the TPD (daily) or TPM (per-minute) limit from the exact
  error text before assuming a key swap will help — only a genuinely
  different account/org gets a new TPD pool.

---

## UI/UX phase, first pass: palette + cursor-reactive effects — 2026-07-21

Per `REBUILD_PROMPT.md` Section 6, explicitly out of scope until the
Definition of Done (Milestone 10) was met — it now is, so this phase
started with its own plan, per the same discipline as every other
milestone.

### Goal
Apply the user's chosen color palette consistently, and add trendy,
cursor-reactive visual interactions (Aceternity-UI-style: cursor
spotlight, animated gradient card borders, pointer-driven 3D tilt),
without changing any backend logic, routes, data contracts, or the
`data-testid` hooks the test suite depends on.

### A real architectural decision made before any code, flagged and
confirmed with the user
All four candidate component libraries (Aceternity UI, Magic UI,
reactbits.dev, 21st.dev) are React + Tailwind + Framer Motion libraries
— none are vanilla-JS/CSS (confirmed via web search:
[Aceternity UI](https://ui.aceternity.com/), requires Next.js 13+,
Tailwind v3+, Framer Motion). Literally adopting one would mean
rewriting the frontend delivery mechanism (Flask+Jinja+vanilla JS →
a React app with a build step) — a scope far beyond a visual reskin.
Presented this tradeoff directly rather than silently deciding; the
user chose to keep the existing architecture and have the visual
effects hand-ported to vanilla CSS/JS instead of adopting React. This
is a deliberate, confirmed deviation from Section 6's literal wording
("use what those libraries already provide"), recorded here so it
isn't mistaken for an oversight later.

### Palette
User re-shared their 29-palette collection and picked (deferring the
final call to this session) — chosen: row 1, column 4 — dark brown /
olive-gold / warm gold / pale gold-cream. Deliberately warm/earthy, and
the user gave an explicit standing instruction to avoid purple and neon
green ("like every other AI website") — confirmed none of the 29
palettes are neon green, and the chosen one and its neighbors avoid
purple entirely. The existing app already leaned this direction (a
warm gold accent on a dark charcoal base, visible in the user's own
screenshots) — this pass sharpens that into a deliberate, fully-defined
scheme via CSS custom properties (`static/style.css`'s `:root` block),
rather than replacing it with something unrelated.

### What was done
- `static/style.css`: `:root` custom properties updated to the chosen
  palette (surfaces, text, accents all re-derived from the swatch).
  `--periwinkle` variable name kept as-is (legacy name from an earlier
  session's rename-in-place) to avoid touching every reference to it —
  documented inline.
- Added a page-wide cursor-spotlight effect: a fixed, pointer-events:none
  layer (`.cursor-spotlight`) whose radial-gradient center tracks
  `--cursor-x`/`--cursor-y`, set continuously by the new
  `static/effects.js` via `requestAnimationFrame`-throttled
  `pointermove` handling.
- Added an animated rotating conic-gradient border to `.card` and
  `.candidate-card` on hover (`@property --border-angle` + a masked
  `::after` pseudo-element), plus a pointer-driven 3D tilt
  (`static/effects.js`, event-delegated on `document` rather than bound
  to individual cards — necessary since candidate cards are wholesale
  replaced via `innerHTML` as jobs complete, so per-element listeners
  would silently stop working the moment cards re-render).
  `prefers-reduced-motion` and `pointer: coarse` (touch) are both
  respected — the spotlight/border-spin skip entirely under reduced
  motion, and the tilt effect skips entirely on touch devices (no
  concept of "hover" to react to).
- Smoothed the progress bar's fill transition (CSS `transition` on the
  `::-webkit-progress-value`/`::-moz-progress-bar` pseudo-elements) so
  progress reads as continuous rather than jumping between ~1.5s
  polling ticks.
- `static/effects.js` (new file): kept deliberately separate from each
  template's existing inline `<script>` (which owns real app
  logic/state) — purely visual, easy to reason about or disable
  wholesale without touching app logic.

### Problems faced
One real bug, found immediately by the existing test suite (not missed):
the explanatory HTML comment added above the new `<script src=...>` tag
in both templates contained the literal substring `<script>` in its own
prose ("separate from the app-logic `<script>` below"), which confused
`tests/test_frontend_js_regression.py`'s regex-based script-block
extraction (`<script>(.*)</script>`, greedy) — it matched from that
comment's `<script>` text through to the real inline script's closing
tag, treating the comment prose as JS and failing with a syntax error.
Fixed by rewording the comment to avoid the literal substring. A good
concrete reminder that a regex-based test extracting from raw HTML
source is sensitive to what appears in comments, not just real tags.

### Test failures and how they were resolved
`test_script_block_is_valid_js[index.html]` and `[candidate.html]` both
failed once, immediately after adding the new `<script src=...>` tags —
root cause and fix exactly as described above. Re-ran: both passed.

### Final test results
- `pytest tests/` — 149/149, 3 consecutive clean runs after the fix.
- `node --check static/effects.js` — valid JS.
- `ruff check .` — clean.
- `git diff` confirms zero `data-testid` attributes removed (grepped
  explicitly for removed `-` lines containing `data-testid`) — all
  changes to `templates/index.html`/`candidate.html` are additive.
- Real smoke test: live gunicorn process (same command as
  `DEPLOY_CHECKLIST.md`), confirmed `GET /`, `GET /static/style.css`,
  `GET /static/effects.js` all return real 200s.

### Not yet done
A real browser visual confirmation from the user — code-level checks
(tests, lint, live-server smoke test) confirm nothing is structurally
broken and the files load correctly, but the actual look (palette,
spotlight, tilt, borders) needs the user's own eyes, same standing
limitation as every other real-browser check this project has needed.

### Notes for future milestones
- If a future session adds more inline HTML comments near `<script>`
  tags in these two templates, avoid the literal substring `<script>`
  in comment prose, or `test_frontend_js_regression.py`'s extraction
  regex will need to be hardened (e.g. anchored to `<script>` at the
  start of a line, or requiring no attributes AND no preceding
  non-tag `<script` text) — noted here rather than fixed defensively,
  since the current regex has worked correctly for every real script
  tag in both templates and over-engineering it isn't warranted yet.
- `static/effects.js`'s event-delegation pattern (bind once on
  `document`, use `closest()` to find the actual target) is the
  correct approach for any future interactive effect on elements that
  get replaced via `innerHTML` — direct per-element binding would
  silently stop working after the first re-render, a class of bug this
  project has already hit once before (candidate-card click handlers
  in `index.html` already use the same delegation pattern for exactly
  this reason).

### Recurring-risk issues
- None new beyond the regex-extraction sensitivity noted above.

### Addendum: user visual confirmation — 2026-07-21
Real browser screenshot provided: palette (dark brown/olive-gold/warm
gold/cream) rendering correctly and consistently across the dropzone,
role card, run bar, and Past Runs list; the "+ Select Files" button and
"Run Analysis" CTA both correctly using the warm gold accent. User's
verdict: "I think its perfect." UI/UX phase closed — no further visual
changes requested.

Separately, visible in the same screenshot: a real (not simulated)
"10/10 resumes failed AI extraction" batch warning, rendering exactly as
designed (Milestone 1) — plain, clearly worded, not a wall of silent
zeros. Consistent with the Groq/Gemini daily quota being tight again
from today's cumulative real testing (same class of event as the
Milestone 8 addendum) — not a new bug, and not something this phase's
scope (visual only) needed to touch. Worth a fresh real-extraction check
right before any live demo, same standing note as before.

---

## Milestone 9: frontend logic wiring — verified structurally present, real click-through handed to the user

### Goal
All backend changes from Milestones 1-4 are actually reachable and usable
from the browser — progress bar, distinct failure banner, past-runs
browser, corrected navigation.

### What was found (code review + Flask test client, not yet a real
browser click-through)
Unlike a typical milestone, most of this one's substance already existed
as a side effect of Milestones 1, 3, and 4 (each added its own frontend
wiring alongside its backend change, rather than deferring all frontend
work to this milestone) — confirmed by direct inspection, not assumed
from the milestone log summaries:
- `templates/index.html` has a real `<progress>` element
  (`data-testid="progress-bar"`), driven by `/api/run/<id>/status`
  polling (Milestone 3).
- A distinct `llm-failure-badge` per-candidate badge and a
  `llm-batch-warning` banner element both exist, reading
  `payload.llm_warning` (Milestone 1).
- A `past-runs-list` section exists, fetching `/api/runs` and reopening
  entries through the same `renderResults()` path live results use — no
  second rendering implementation (Milestone 4).
- `templates/candidate.html`'s `window.close()` / fallback navigation
  (Milestone 5) is unchanged and still correctly wired to
  `window.open()`-initiated detail tabs.
- `GET /`, `GET /candidate`, `GET /api/jds` all confirmed returning 200
  via a fresh Flask test-client check this session (not assumed from
  prior milestones).
- No CSS/visual files were touched by this session at all (confirmed via
  `git status` and this session's own edit history) — the "no visual
  work in this phase" rule holds trivially, since none of this
  milestone's remaining work touches styling.

### Not yet done
The exit criteria explicitly requires one real browser click-through
(upload → progress bar visibly updates → results appear progressively →
a deliberate-failure run shows the banner → past runs list shows the run
→ reopening it renders correctly) — this cannot be performed from this
sandbox (no browser access), same limitation already established and
handled the same way for Milestone 5. Handed to the user as part of the
same end-of-day handoff as Milestone 8's real load test.

### Final test results
- `pytest tests/` — 149/149 (unchanged, no product code modified for
  this milestone; all wiring already existed).
- Route-level check: `/`, `/candidate`, `/api/jds` all 200 via a fresh
  Flask test-client run this session.
- Real browser click-through: pending, handed to the user.

### Notes for future milestones
- When a milestone's backend-adjacent work (Milestones 1/3/4 here) is
  built with its frontend wiring alongside it rather than deferred, a
  later "frontend wiring" milestone can end up being mostly a
  verification pass rather than new construction — worth checking for
  this explicitly (as done here) before assuming a milestone needs new
  code just because it hasn't been formally closed yet.

### Recurring-risk issues
- None new. Same standing note as Milestone 5: any exit criteria
  requiring a real browser must be handed to the user with exact,
  numbered steps — not skipped, not marked done from code review alone.
