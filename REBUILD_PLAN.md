# ParseLoom Rebuild — Milestone Plan

Written 2026-07-20. Produced after reading, in order: `PROJECT_CONTEXT.md`,
`DESIGN_DECISIONS.md`, `WEB_APP_PLAN.md`, `SESSION_HANDOFF.md`,
`RELIABILITY_SCALE_ANALYSIS.md`, and the actual code (`app.py`, `main.py`,
`src/ai_client.py`, `src/extraction/llm_extract.py`, `src/matching/scorer.py`,
`src/extraction/pdf_reader.py`, `src/models.py`, `templates/index.html`,
`requirements.txt`). No implementation code has been written yet — this is
the plan required by `REBUILD_PROMPT.md` Section 3, submitted for review
before any milestone starts.

**Decisions locked with the user before writing this plan** (see chat):
- Provider: try Groq first, fall back to Gemini on failure; if that combo
  proves unreliable, collapse to Groq-only (my recommendation) and say so
  explicitly when it happens.
- Real API quota may be spent on the 40-resume load test and the accuracy
  fixture suite — no mocking-by-default requirement.
- Deploy target: a free-tier host (Render, per `SESSION_HANDOFF.md` history)
  — must be designed around a free tier's constraints, not a paid one.
  Ephemeral disk on free tiers is a real, documented risk (see Milestone 4).
- In-progress job state: in-memory is enough, no requirement to survive a
  process restart mid-batch.
- **New scope, explicitly requested, beyond `WEB_APP_PLAN.md`'s original
  "no database" design:** completed run results must persist across days
  and be browsable later ("5 days ago, 10 days ago, any JD") via a button
  in the UI. This is a real feature addition, not implied by the original
  five files — called out here so it isn't silently smuggled in.
- Batch processing must show results as they complete in bounded waves —
  workers pick up the next resume as soon as a slot frees, not "wait for
  all 8, then show, then start the next 8." Realized as a bounded worker
  pool with progressive/streaming result delivery, not literal discrete
  rounds (see Milestone 3).

---

## 0. Understanding of the LLM pipeline contract (required by Section 4, before any pipeline code)

**Request/response contract, per provider, as implemented today in `src/ai_client.py`:**

- **Groq** (`_call_groq`): OpenAI-compatible REST, `POST
  https://api.groq.com/openai/v1/chat/completions`, bearer auth,
  `response_format: json_object`. Errors: HTTP 429 (rate limit), 500-504
  (transient), non-2xx other (config/bad request), `requests.RequestException`
  (timeout/DNS/connection), and a "200 OK but the JSON body doesn't have the
  expected shape" case (`KeyError`/`IndexError` on `data["choices"][0]...`).
- **Gemini** (`_call_gemini`): `POST
  generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`,
  key via `x-goog-api-key` header (already fixed to not leak into URLs —
  keep this fix). Same error classes as Groq, plus a confirmed historical
  failure mode: silent JSON truncation from `thinkingConfig` eating the
  output budget (already fixed with `maxOutputTokens`/`thinkingBudget: 0` —
  keep this fix, add a regression test for it).
- **Both:** `_post_with_retry` retries on `{429,500,502,503,504}` with
  exponential backoff (1/2/4/8s capped at 15s), 4 retries, 30s timeout per
  attempt. After retries exhausted, raises `LLMError`.

**Real, measured rate limits (fetched from `console.groq.com/docs/rate-limits`
today, not assumed):**

| Model | RPM | RPD | TPM | TPD |
|---|---|---|---|---|
| `llama-3.3-70b-versatile` (Groq free) | 30 | 1,000 | **12,000** | 100,000 |

The current code's 4-worker cap was sized against RPM alone ("avoid bursting
past the per-minute rate limit," per the comment in `app.py`). That reasoning
was incomplete: **TPM is the tighter real constraint**. A typical resume
(system prompt ~300 tokens + redacted resume body ~600–1,200 tokens + JSON
output ~300–600 tokens) costs roughly 1,200–2,100 tokens per call. At 12,000
TPM, that caps sustainable throughput at **roughly 6–9 requests/minute**, well
under the 30 RPM ceiling. The concurrency design in Milestone 2 is built
against the TPM number, not the RPM number, because TPM is what will actually
trip first on real resumes.

Gemini (`gemini-flash-latest`) has no equivalently documented per-minute cap
confirmed here, but `PROJECT_CONTEXT.md` Section 11 already confirmed a real
20 requests/day/model cap on the free tier via a live 429 — far too low to be
a real second lane for a 40-resume batch. It's used as a per-request
failover only (a handful of overflow calls), never load-bearing.

**How each error mode maps to a distinct data-model state (fixes Section 2,
item 1):** see Milestone 1 — this is the first thing built, before any
concurrency/scaling work, because every later milestone's tests depend on
being able to tell "the provider failed" apart from "the resume is thin."

**Fixture set for accuracy verification:** 5–10 resumes from
`data/real_resumes/` (already in the repo, already real PDFs from the actual
event dataset) will be hand-reviewed and their expected `full_name`,
`skills`, `cgpa_10pt` recorded in a checked-in fixture file. Built in
Milestone 7, after the failure-state work (Milestone 1) exists — otherwise a
"wrong" fixture result can't be told apart from a silent provider failure.

**Caching decision:** content-hash (SHA-256 of uploaded file bytes) → cached
extraction result, in-memory dict for now (consistent with the "in-memory is
enough" decision), keyed off file bytes not filename. This is a pure
dev/test-speed and quota-conservation win with no correctness risk (identical
bytes → identical extraction), and directly serves the "real calls are fine"
decision by making repeat test runs during development free after the first
pass. Built in Milestone 2 alongside the concurrency rework, since both touch
the same call site.

---

## Milestone 0 — Process scaffolding + eliminate the main.py/app.py duplication

**Goal:** One canonical parsing pipeline function exists and is imported by
both `main.py` and `app.py`, with zero behavior change from today — proves
the refactor is safe before any new logic is layered on top of it.

**Inputs needed:** Current `main.py::parse_one_resume` and
`app.py::parse_one_resume` (confirmed byte-for-byte duplicated except for a
docstring), current passing test suite (`tests/test_scorer.py`,
`test_grade_normalizer.py`, `test_skill_matcher.py`).

**Implementation scope:** Create `src/pipeline.py` with the single
`parse_one_resume(path: str) -> ParsedResume` function, imported by both
`main.py` and `app.py`. Delete both duplicates. **Explicit decision per
Section 3's requirement to decide deliberately:** yes, this duplication is
removed via a shared module — there is no reason for two copies of the same
logic in a from-scratch rebuild. Nothing else changes in this milestone — no
new fields, no new failure states, no timing yet (that's Milestone 1). Create
`MILESTONE_LOG.md` in this milestone.

**Not included:** any behavior change, any new tests beyond confirming
identical output to before.

**Tests required:**
- Unit: existing 29 tests still pass unmodified.
- Integration: run `main.py` against `data/mock_resumes/` (small, free —
  synthetic PDFs, no LLM calls needed for the ones that hit `Failed` before
  reaching extraction) and diff output against a pre-refactor baseline
  captured before the change, to confirm byte-identical `ParsedResume`
  output for the same inputs.
- Code health: `grep` confirms no remaining duplicate definition of
  `parse_one_resume` anywhere in the repo.

**Exit criteria:** `pytest tests/` green, `main.py` and `app.py` both import
from `src/pipeline.py`, no second definition of `parse_one_resume` exists,
diff against pre-refactor baseline output is empty.

---

## Milestone 1 — Explicit, distinct LLM-failure state (Section 2, item 1)

**Goal:** A resume whose LLM call genuinely failed (rate limit, bad key,
timeout, malformed JSON) is structurally and visually distinguishable, at
every layer, from a resume that parsed thinly on its own merits.

**Inputs needed:** Milestone 0's `src/pipeline.py`. `src/models.py`'s
`ParsedResume`/`ScoreResult` dataclasses.

**Implementation scope:**
- `ParsedResume` gets a new field: `llm_call_failed: bool = False` and
  `llm_failure_reason: str | None = None`, additive — `parse_status` keeps
  its existing three values (`Clean`/`Partial`/`Failed`) for backward
  compatibility with the CLI's documented output shape, but
  `llm_call_failed=True` is now checked independently everywhere a UI or
  report renders status. A resume where the LLM call itself errored gets
  `parse_status = "Partial"` **and** `llm_call_failed = True` — the two
  together are what were previously conflated into a bare `"Partial"`.
- `src/pipeline.py::parse_one_resume` catches `LLMError`, sets both new
  fields, and records the real (scrubbed) error string in
  `llm_failure_reason`.
- `src/matching/scorer.py::score_candidate`: when `llm_call_failed` is true,
  the reasoning bullets say so explicitly ("AI extraction failed —
  {reason} — this is not a reflection of resume quality"), not the generic
  "resume only partially parsed" text used for genuinely thin content.
  `ScoreResult` gets a new `llm_call_failed: bool` field, passed through.
- `/api/run` (and the CLI's `write_parse_quality_report`): count
  `llm_call_failed` resumes in a batch; if more than half the batch hit it,
  return/print a distinct top-level warning ("N/M resumes failed AI
  extraction — likely a provider outage or rate limit, not resume quality")
  rendered above individual results, not buried per-card.
- Timing instrumentation: a small `time_stage(resume_file, stage)` context
  manager in `src/pipeline.py`, wrapping PDF extraction, OCR (when
  triggered), and the LLM call. Logs `resume_file, stage, duration_ms` at
  INFO level via the existing `logging` setup. This is infrastructure other
  milestones (2, 8) depend on to answer "where did the time go," so it's
  built now even though the concurrency rework is later.

**Not included:** concurrency/backoff changes (Milestone 2), UI badge
styling beyond a functional, unstyled distinction (deferred to the later
UI/UX phase per `REBUILD_PROMPT.md` Section 1 — this milestone only needs
the data to reach the frontend correctly labeled, e.g. a plain `<span
class="llm-failure-badge">`).

**Tests required:**
- Unit: `score_candidate` produces the distinct reasoning text when
  `llm_call_failed=True` vs. a genuinely thin `Partial` resume with
  `llm_call_failed=False`.
- Integration: real PDF through `src/pipeline.py::parse_one_resume` with
  `AI_PROVIDER` pointed at a deliberately invalid key — confirms
  `llm_call_failed=True`, `parse_status="Partial"`, and the reason string is
  scrubbed of the key value.
- LLM-pipeline-specific: simulated 429 (mocked `requests.post` response),
  simulated 500, simulated timeout (`requests.Timeout`), simulated malformed
  JSON body — each must independently produce `llm_call_failed=True` with a
  reason string identifying which failure mode occurred, not a generic
  message.
- Regression test for Section 2 item 1 specifically: three resumes with a
  poisoned API key must NOT produce three "genuinely different but
  identically empty" results indistinguishable from real thin content — the
  test asserts `llm_call_failed=True` on all three and a batch-level warning
  is present in the response.

**Exit criteria:** All above tests pass. Manually confirmed: pointing
`GROQ_API_KEY`/`GEMINI_API_KEY` at invalid values and running 3 resumes
through `/api/run` produces a clearly labeled failure state in the JSON
response, not a wall of `0` scores.

---

## Milestone 2 — Rate-limit-aware concurrency, dual-provider failover, content-hash caching

**Goal:** Concurrency is set against Groq's real measured 12K TPM ceiling
(not a guessed RPM number), Gemini is used as an automatic per-request
failover (not a load-bearing second lane), and identical file bytes are
never re-sent to the LLM twice in the same server process.

**Inputs needed:** Milestone 1's failure-state model (so a failed-over or
ultimately-failed call is correctly labeled). The measured Groq numbers in
Section 0 above.

**Implementation scope:**
- Replace the fixed `max_workers=4` `ThreadPoolExecutor.map()` call with a
  bounded worker pool where **workers pull the next resume as soon as a slot
  frees**, not discrete rounds — `concurrent.futures.ThreadPoolExecutor` with
  `as_completed()` already behaves this way once `max_workers` is set
  correctly; the "wait for all 8 before starting the next 8" behavior in the
  current code is an artifact of `.map()` preserving input order for
  rendering, not a real batching requirement. Switch to `as_completed()` and
  handle result ordering downstream (sort by score/rank at render time, not
  by completion order).
- `max_workers` set to **6** by default (documented rationale: 12,000 TPM ÷
  ~1,800 tokens/call ≈ 6.7 sustainable calls/minute; 6 concurrent workers
  with realistic per-call latency keeps sustained throughput under the TPM
  ceiling with headroom for retries, rather than bursting to the RPM ceiling
  of 30 and immediately eating 429s). This number is documented as a
  starting point to be corrected by Milestone 8's real load test, not
  treated as final until measured.
- `call_llm`: try Groq first; on `LLMError` from Groq specifically (not from
  a bad response mid-decode), retry once against Gemini before giving up.
  Both failing → `llm_call_failed=True` with a reason noting both providers
  were tried. This directly implements the "use both, fall back to your
  recommendation if it doesn't work" decision — if Milestone 8's load test
  shows Gemini's fallback attempts add meaningful latency or unreliability
  under real batch conditions, collapse to Groq-only and document why in
  `MILESTONE_LOG.md`, not silently.
- Content-hash cache: `hashlib.sha256(file_bytes).hexdigest()` → cached
  `ParsedResume` (or at minimum the LLM extraction result), in-memory dict
  on the Flask app object, checked before calling `parse_one_resume`'s LLM
  step. Documented as dev/test-speed and quota-conservation only, explicitly
  not a correctness feature (a resume's content genuinely doesn't change
  between runs, so this is safe, not a shortcut that risks staleness).

**Not included:** persistent (disk-backed) caching — in-memory only, per the
same reasoning as job-state in Milestone 3. Async job architecture itself
(Milestone 3) — this milestone only changes how one batch's LLM calls are
scheduled internally, not the `/api/run` request/response shape yet.

**Tests required:**
- Unit: cache hit/miss logic (same bytes → cache hit, different bytes → miss)
  with no real LLM calls, using an injectable fake `call_llm`.
- Integration: real small batch (3-5 resumes from `data/real_resumes/`)
  through the new pooled execution, confirming order-correct final output
  despite out-of-order completion.
- LLM-pipeline-specific: mocked Groq 429 on every call, confirm Gemini
  fallback actually fires (assert Gemini's call function was invoked) and
  produces a result rather than immediate `llm_call_failed`; mocked failure
  on both providers, confirm `llm_call_failed=True` with a reason mentioning
  both.
- Load/concurrency (small-scale, done properly at full scale in Milestone
  8): a synthetic-delay test (no real LLM calls, matching the existing
  pattern from `SESSION_HANDOFF.md` item 8) confirming 6 workers run
  genuinely concurrently and a 7th+ resume waits for a slot rather than
  firing immediately.

**Exit criteria:** All tests pass. A real 6-resume batch against Groq
completes with individually-timed stage logs confirming no resume waited
idle for an already-free worker slot.

---

## Milestone 3 — Async job architecture with progressive/streaming results

**Goal:** `/api/run` returns immediately with a `job_id`; a polling endpoint
returns candidates as they finish, in bounded-concurrency waves, so the
browser shows real progress instead of blocking on the whole batch — and
survives a slow batch without hitting a reverse-proxy timeout on a free host.

**Inputs needed:** Milestone 2's pooled execution and failure-state model.

**Implementation scope:**
- `POST /api/run`: validates JD + files, saves uploads, generates `job_id`,
  starts a background `threading.Thread` running the batch, returns
  `{job_id}` immediately (target: well under 1s, since this no longer waits
  on any LLM call).
- In-memory job store: `dict[job_id, JobState]` on the Flask app object.
  `JobState` holds: status (`running`/`done`/`error`), a list of completed
  candidate results (appended to as each resume finishes, via
  `as_completed()` from Milestone 2), total count, and the final shortlist
  once all resumes are done. Per the user's explicit decision, this is
  in-memory only — a process restart mid-batch loses progress. **Documented
  as an accepted limitation of the free-tier deploy target**, not silently
  glossed over: if the host recycles the process mid-batch, the job is
  gone and the user has to re-run. Flagged again in Milestone 4's
  discussion of the same host's disk behavior.
- `GET /api/run/<job_id>/status`: returns `{status, completed: N, total: M,
  candidates_so_far: [...]}` — the frontend polls this every ~1.5s and
  renders/appends candidates as they arrive, satisfying the "8 move forward
  and show, next ones join as they finish" requirement via continuous
  polling rather than discrete rounds.
- `GET /api/run/<job_id>/result`: same final payload shape `/api/run`
  returns today, once `status == "done"`.
- Frontend results view is not replaced/cleared until a new run is
  submitted (satisfies "output should not be overdone until a new JD
  comes") — this is additive to the existing `localStorage`-based restore
  pattern already in `index.html`, not a rewrite of that mechanism.
- `MAX_FILES_PER_REQUEST`: since the upload request itself no longer runs
  the batch synchronously, the cap is re-justified as an upload-sanity limit
  (total request size already capped at 25MB via `MAX_CONTENT_LENGTH`), set
  to **80** (documented: comfortably above the real 54-resume event dataset
  and the 40-resume target, with headroom, while still bounded against a
  pathological single request). Batches the user submits above this (rare,
  but handled transparently) are chunked client-side into sequential
  `/api/run` calls whose job results are merged in the same polling view —
  the user never has to manually split an upload.

**Not included:** disk-persisted job state (explicitly decided against);
Server-Sent Events (polling is simpler to get right and sufficient at this
scale, matches `WEB_APP_PLAN.md`'s own "minimum viable: polling" framing).

**Tests required:**
- Unit: `JobState` transitions (`running` → `done`/`error`), candidate
  accumulation logic.
- Integration: Flask test client — `POST /api/run` returns a `job_id`
  quickly (assert response time), poll `/status` until `done`, confirm
  candidate count matches upload count and final `/result` shape matches
  today's `/api/run` synchronous shape (no schema drift for the frontend or
  any judge comparing to CLI output).
- Load/concurrency: real 10+ resume batch, poll throughout, assert
  `candidates_so_far` grows monotonically and individual candidates appear
  before the whole batch finishes (proves progressive delivery, not a
  disguised synchronous wait).
- Regression test for Section 2 item 4 specifically: a batch run under a
  simulated slow-provider condition (artificial delay injected in a test
  double) must not block the initiating HTTP request past a few seconds,
  proving the synchronous-blocking bug is actually fixed, not just faster.

**Exit criteria:** All tests pass. A real batch run against Groq shows
individual candidates appearing in the polled response well before the full
batch completes, confirmed by a timestamped log of when each candidate
became visible via `/status`.

---

## Milestone 4 — Persistent run history (new scope, explicitly requested)

**Goal:** A completed run (JD + full results) can be reopened days later
from a "past runs" view, addressing the user's explicit ask — this is new
scope beyond `WEB_APP_PLAN.md`'s original "no database" design, called out
here as a deliberate expansion, not an accidental one.

**Inputs needed:** Milestone 3's completed job results (the same payload
`/api/run/<job_id>/result` produces).

**Implementation scope:**
- SQLite (`stdlib sqlite3`, zero new dependency, file-based, matches the
  project's "minimal deps" philosophy) — one table: `runs(id, created_at,
  jd_role, jd_snapshot_json, result_json, resume_count)`. Written once a job
  reaches `done`.
- `GET /api/runs`: list past runs (id, date, JD role, candidate count) for a
  "Past Runs" browse view.
- `GET /api/runs/<id>`: full stored result, rendered through the exact same
  frontend rendering code path as a live run (no second rendering
  implementation to drift from the first).
- **Explicit, documented risk — must be surfaced to the user, not silently
  accepted:** most free-tier hosts (Render's free web service tier
  specifically) do not guarantee persistent disk across redeploys, and may
  wipe local files on a cold restart after extended idle. This means
  `runs.db` **may not survive indefinitely on a free host** depending on
  which free host is ultimately used. Mitigation built alongside the
  feature, not after: a "Download this run as JSON" button on every result
  view, so the user always has an export escape hatch independent of
  whether server-side history persists long-term. This limitation and its
  mitigation get a dedicated `MILESTONE_LOG.md` entry so it's never
  rediscovered as a surprise during a demo.

**Not included:** editing/deleting past runs, search/filtering beyond a
simple date-sorted list, multi-user isolation (this remains a
single-operator tool per `WEB_APP_PLAN.md` Section 6 — that scope decision
still stands, only "does a completed run persist" changed).

**Tests required:**
- Unit: SQLite read/write round-trip for a run record.
- Integration: run a real small batch end to end via Milestone 3's job
  flow, confirm it appears in `/api/runs`, confirm `/api/runs/<id>` returns
  a byte-identical result to what `/api/run/<job_id>/result` returned live.
- Restart-survival test: write a run, restart the Flask process (simulated
  in-test by closing and reopening the SQLite connection, not literally
  killing the process), confirm the run is still readable — proves the
  *database* layer itself is durable even though in-memory job state
  (Milestone 3) is not; these are two different durability guarantees and
  the tests must not conflate them.
- Security: confirm `result_json` written to SQLite never contains a raw
  API key (reuses the existing `_scrub_secrets` guarantee — add an explicit
  test asserting a poisoned failure reason is scrubbed before it reaches the
  database, not just before it reaches `parse_notes`).

**Exit criteria:** All tests pass. A run submitted today is retrievable via
`/api/runs/<id>` tomorrow (verified by literally waiting or by timestamp
manipulation in a test), and the JSON export button produces a file that
matches the stored `result_json` byte for byte.

---

## Milestone 5 — Cross-tab "Back to results" fix (Section 2, item 6)

**Goal:** Clicking "Back to results" on the candidate detail page returns
the user to the original tab (via `window.close()`), not a re-render inside
the detail tab, with a documented fallback when the tab isn't opener-owned.

**Inputs needed:** Existing `templates/candidate.html`/`index.html` JS
pattern (already uses `window.open()` from a script, which is required for
`window.close()` to be permitted by the browser — this part of the existing
design is correct and kept).

**Implementation scope:**
- `candidate.html`: replace the plain results-navigation link with a click
  handler: `window.close()`, then a `setTimeout` fallback (e.g. 150ms) that
  checks whether the window actually closed (`window.closed`) and, if not,
  navigates to `/` instead (which still restores the last run via
  `localStorage`, per the existing pattern) — covers the case where the tab
  wasn't opener-owned (e.g. manually opened, or opener severed by browser
  privacy settings).
- No structural HTML changes needed beyond the button's behavior — this is
  a logic-only fix, consistent with Section 1's "logic only, not visual
  redesign" scope for this phase.

**Not included:** any visual change to the button itself.

**Tests required:**
- Since this is a real-browser DOM/window behavior, it cannot be verified
  by `pytest` alone. Documented as requiring one real click-through
  (Chrome/Safari) as part of this milestone's exit criteria, consistent
  with `SESSION_HANDOFF.md`'s own admission that no browser automation
  exists yet for this app. A `Read`-level code review confirms the fallback
  logic itself is correct (no `window.close()` call left unguarded).
- Regression note: `SESSION_HANDOFF.md` records the prior, incomplete fix
  (sessionStorage → localStorage) as solving data availability but not
  navigation. This milestone's exit criteria explicitly re-verifies both:
  data is available in the detail tab (unchanged), AND "Back to results"
  closes the tab rather than re-rendering.

**Exit criteria:** One real click-through in a real browser: upload →
run → open a candidate's detail page → click "Back to results" → confirm the
detail tab closes and focus returns to the original tab (not a page reload
inside the same tab).

---

## Milestone 5.5 — Shortlist score floor + shareable candidate detail links (added mid-stream at user's request)

Same convention as the Excel-export feature added between Milestones 3 and
4: this wasn't in the original plan, surfaced from real usage (a real run
where a zero-skill-overlap candidate filled an open shortlist slot, and a
request to be able to open a specific candidate's detail page directly from
the exported spreadsheet), and is scoped and logged the same way any other
milestone is rather than patched in silently.

**Goal:** Two independent fixes.

(A) A candidate with zero measurable skill overlap with the JD can no longer
occupy a "we recommend this person" shortlist slot just because a slot
happens to be open — trustworthiness of the shortlist itself, not a UI
issue.

(B) The Excel export can link to a specific candidate's full detail page,
and that link actually works for anyone who opens it, not just the browser
tab that ran the batch — closes a real gap where `/candidate` had no
server-side data source at all.

**Inputs needed:** `src/matching/shortlist.py` (A), `src/output/xlsx_export.py`
+ `app.py`'s two export routes + `templates/candidate.html` (B). Milestone 4's
`history` module and `job_store` already provide the server-side lookups
needed for (B) — no new storage.

**Implementation scope:**

(A) — `build_shortlist()`:
- A score of exactly `0` means `skill_subscore == 0` (zero required AND zero
  preferred skill matches — see `scorer.py`; the completeness multiplier
  can't lift a `0` skill_subscore above `0` either way). Candidates at or
  below this floor are never placed into `shortlist`, regardless of open
  slots — routed to `reserve` instead, same as a below-CGPA-minimum
  candidate: still scored, still fully visible, never hidden (Section
  10.5's human-in-the-loop principle — this is a visibility rule, not a
  filtering-out rule).
- `summary` gains `slots_unfilled` (`jd.slots - len(shortlist)`, `0` if not
  positive) so an honestly-short shortlist is a visible, labeled fact, not
  something a viewer has to notice by counting rows.
- `PROJECT_CONTEXT.md` Section 6 (scoring algorithm) updated to document
  this floor — it was previously undocumented that shortlist had no minimum
  score gate at all.

(B) — shareable detail links:
- `templates/candidate.html`: extend the existing data-loading logic (which
  currently only reads `localStorage['parseloom_last_run']`) to also accept
  `?job_id=` (fetches `/api/run/<job_id>/result`, for a still-in-memory live
  job) or `?run_id=&client_id=` (fetches `/api/runs/<run_id>?client_id=`,
  for a persisted historical run) query params, falling back to the
  existing `localStorage` path when neither is present. This is additive —
  the current same-tab `window.open()` + `window.close()` flow from
  Milestone 5 is completely unchanged.
- `src/output/xlsx_export.py::build_workbook()` gains an optional
  `detail_link_base` parameter (a full URL prefix, e.g.
  `f"{request.host_url}candidate"`, plus either `job_id` or `run_id`+
  `client_id`) and adds a "Details Link" hyperlink column to the Shortlist
  and Reserve sheets (Needs Review has no `details` entry to link to, per
  existing behavior — unchanged). When not supplied (e.g. existing tests),
  behavior is identical to today — no link column, matching current output
  exactly, so this is backward compatible.
- `app.py`'s two export routes (`/api/run/<job_id>/export.xlsx` and
  `/api/runs/<run_id>/export.xlsx`) pass `request.host_url` + the relevant
  id(s) into `build_workbook()`.
- **Explicitly not changed:** the original uploaded PDF is still deleted
  immediately after each job (per the standing PII-minimization decision).
  The link opens the structured extraction/scoring detail page, not the raw
  file — confirmed with the user as the intended scope, not a shortfall.
- **Known limitation, documented not hidden:** a `job_id`-based link only
  works while that job is still in `job_store`'s TTL window; once it's
  expired, only a `client_id`-scoped run saved to history remains
  retrievable. This matches every other place in this app that already
  draws the same live-vs-historical distinction (e.g. the two separate
  export routes already existing) — not a new limitation, just the first
  time a *link* (not just a button in the already-open page) is exposed to
  it.

**Not included:** retaining uploaded PDFs, any change to the Milestone 5
same-tab navigation flow, a Needs Review detail link (no detail data exists
for a failed parse to link to).

**Tests required:**
- `tests/test_shortlist.py`: a zero-score, CGPA-eligible candidate is
  excluded from `shortlist` even with open slots; ends up in `reserve`;
  `summary.slots_unfilled` is correct when too few real candidates exist to
  fill every slot; unchanged behavior (existing tests) for CGPA-based
  exclusion and the `llm_call_failed` passthrough.
- `tests/test_xlsx_export.py`: `build_workbook()` with `detail_link_base` +
  `job_id` produces a hyperlink cell with the expected URL on shortlist/
  reserve rows; same with `run_id`+`client_id`; omitting `detail_link_base`
  produces byte-for-byte the same sheets as before (backward compatibility,
  not just "doesn't crash").
- `tests/test_frontend_js_regression.py`'s existing `node --check` syntax
  test naturally covers `candidate.html`'s extended script.
- One more real click-through, since the whole point of (B) is a link that
  works *outside* the originating tab: open a run, export the spreadsheet,
  copy a candidate's Details Link, open it in a **new private/incognito
  window** (no shared `localStorage`) — confirm the candidate's real data
  renders, not "Candidate not found."

**Exit criteria:** All new + existing tests pass. The private-window
click-through confirms a real, working, shareable link. `slots_unfilled`
visibly reports a non-zero value on a real run where a JD's slots exceed
the number of candidates with any real skill overlap.

---

## Milestone 6 — Fixture-based extraction accuracy suite (Section 2, item 7)

**Goal:** "Is the data actually correct" becomes a checkable, automated
pass/fail against real resumes with known-correct expected values, instead
of eyeballed from screenshots.

**Inputs needed:** Milestone 1's failure-state distinction (so a fixture
test failure is provably a real extraction miss, not a masked provider
failure). Real PDFs already in `data/real_resumes/`.

**Implementation scope:**
- Select 8 real resumes from `data/real_resumes/` spanning: a clean
  single-column resume, a confirmed two-column resume (per
  `PROJECT_CONTEXT.md` Section 11, 31/54 real resumes triggered column
  splitting — pick one), a resume with a percentage-format CGPA if one
  exists in the real set (Section 11 notes only CGPA-10 format was
  confirmed on real data — if none exists, supplement with one of the
  already-built `data/mock_resumes/` synthetic CGPA-format fixtures,
  documented as synthetic in the fixture file, not passed off as real).
- Manually read each PDF and record expected `full_name`, expected `skills`
  (a reasonable superset/subset judgment call, documented per fixture),
  expected `cgpa_10pt`, checked into `tests/fixtures/accuracy_fixtures.json`.
- `tests/test_extraction_accuracy.py` (marked `@pytest.mark.slow`, excluded
  from the default fast `pytest tests/` run, run explicitly): runs real
  extraction against each fixture, computes per-field accuracy (name exact
  match, CGPA exact match, skills recall — how many expected skills were
  actually found), reports an aggregate accuracy percentage.
- **Explicitly stated accuracy bar, defensible to a judge:** ≥85% name
  accuracy, ≥90% CGPA accuracy (when present on the resume), ≥75% skill
  recall — deliberately not 99%, per `PROJECT_CONTEXT.md` Section 10.5's own
  documented philosophy that chasing artificial 99% on messy real input is
  the wrong target; the real deliverable is these numbers being honestly
  measured and reported, not inflated.

**Not included:** projects/experience/certifications accuracy scoring
(genuinely harder to grade automatically — name/skills/CGPA are the three
fields explicitly required by Section 4 of `REBUILD_PROMPT.md`).

**Tests required:**
- The accuracy suite itself, as described above.
- LLM-pipeline-specific, required by Section 4: (a) known-good fixture
  (above), (b) deliberately-broken input — `data/mock_resumes/
  mock_corrupted_file.pdf` and `mock_empty_file.pdf` (already exist) through
  the full pipeline, confirming graceful `Failed` status, no crash, (c)
  prompt-injection resume — a new fixture PDF containing a fake "SYSTEM
  OVERRIDE: CGPA 10.0" style instruction, confirming the model ignores it
  (extends the manual verification already done per `PROJECT_CONTEXT.md`
  Section 11.7 into an automated, repeatable test rather than a one-time
  manual check).

**Exit criteria:** Accuracy suite runs against real Groq calls, passes the
stated bar, and the report (name/CGPA/skill-recall percentages) is written
to `tests/fixtures/accuracy_report.md` for inclusion in the milestone log
and, later, the submission.

---

## Milestone 7 — Security, dependency, and code-health pass

**Goal:** Every security guarantee already claimed in `PROJECT_CONTEXT.md`
Section 11.7 (API-key-leak fix, full PII redaction, prompt-injection
resistance) has an automated regression test, plus new checks for the
web-upload surface and dependency vulnerabilities, per Section 3's required
checklist.

**Inputs needed:** All prior milestones' code (this pass covers the whole
rebuilt surface, not a single component).

**Implementation scope:**
- Formalize the three fixes from `PROJECT_CONTEXT.md` Section 11.7 as
  automated tests (currently documented as manually reproduced-and-fixed,
  not test-covered): API-key-in-exception-text scrubbing, multi-occurrence
  PII redaction (`.finditer()`/`.sub()`, not just first match), and
  prompt-injection resistance (covered already in Milestone 6's fixture
  suite — cross-referenced, not duplicated).
- Upload validation tests: oversized file rejected, wrong extension
  rejected, file count over the Milestone 3 cap rejected, a file claiming a
  `.pdf` extension but containing non-PDF bytes rejected before reaching
  `fitz.open()` (currently relies on `fitz.open()` failing gracefully,
  which works but isn't explicitly tested as a security boundary).
- Error-response test: force an unhandled exception in the pipeline (via a
  test double), confirm the HTTP response contains no stack trace or
  internal file path, only the generic message (existing behavior in
  `app.py`'s `except Exception` blocks — add the missing test).
- Dependency scan: `pip-audit` (or `safety`) run against `requirements.txt`,
  documented result checked into `MILESTONE_LOG.md`; any finding either
  fixed (version bump) or explicitly accepted with a one-line reason.
- Lint/type-check: `ruff` (fast, matches "minimal tooling" philosophy) for
  lint; `mypy` only if it doesn't fight the codebase's deliberate
  dataclass-not-pydantic simplicity — if `mypy` produces excessive noise
  against the existing loosely-typed style, document that decision rather
  than forcing type annotations everywhere for their own sake.
- Dead-code check: confirm Milestone 0's deduplication held (no reintroduced
  second `parse_one_resume`), confirm no leftover unused imports/functions
  from the rebuild process itself.

**Not included:** a full penetration test or anything beyond the specific,
named risks already identified in this project's own history — scope is
bounded to what Section 3 of `REBUILD_PROMPT.md` explicitly lists.

**Tests required:** all of the above, each as a named, independently
runnable test — listed exhaustively since this milestone's entire job is
"tests," not new features.

**Exit criteria:** `pip-audit` clean or all findings documented+accepted,
`ruff check` clean, all named security regression tests passing, dead-code
check clean.

---

## Milestone 8 — Full 40-resume load test + simulated full-outage test (Definition of Done, Section 5)

**Goal:** Prove, with real evidence (not "it eventually finished"), that a
real 40-resume batch completes within a stated time budget with visible
progress, and that a full provider outage produces a clearly labeled
non-zero-looking failure state across the whole batch.

**Inputs needed:** Every prior milestone (this is the integration point for
all of them). At least 40 real PDFs (`data/real_resumes/` already has more
than 40).

**Implementation scope:** No new product code expected — this milestone is
running the system built in Milestones 0–7 against real conditions and
recording what actually happens, fixing anything that breaks in the
process (with the fix and its story going into `MILESTONE_LOG.md`, per
Section 3a's requirement to capture the full arc, not just the clean end
state).

- Real 40-resume run via the Milestone 3 async job flow, polled throughout,
  with per-stage timing (Milestone 1) captured to derive and **state** an
  actual time budget (e.g. "40 resumes complete in under N minutes at 6
  concurrent workers" — N measured, not guessed) — this becomes the
  documented, tested time budget Section 5 requires.
- Confirm the Milestone 2 concurrency number (6 workers) actually holds up
  — if the real run shows 429s slipping through or throughput different
  from predicted, retune `max_workers` here and document the correction
  (this is explicitly anticipated in Milestone 2's scope as "a starting
  point to be corrected by real load testing").
- Simulated full-outage run: both `GROQ_API_KEY` and `GEMINI_API_KEY` set to
  deliberately invalid values, same 40-resume batch, confirm every resume
  reaches `llm_call_failed=True` with the batch-level warning from
  Milestone 1 surfaced prominently — visually and structurally distinct
  from a real low-score result, not a wall of `0`s.

**Not included:** testing on the actual free-tier deploy host itself (that's
implicitly part of "deployed and works," which is a separate, later
deployment-verification step outside this document's scope — this milestone
tests the load/concurrency/failure behavior locally against the real APIs,
not Render's specific infrastructure quirks).

**Tests required:**
- The 40-resume real run itself, with timing evidence retained (not just a
  pass/fail — the actual numbers go in `MILESTONE_LOG.md`).
- The simulated full-outage run, with the response payload's failure
  labeling retained as evidence.
- Regression assertions for Section 2 items 3 and 4 specifically: confirm
  concurrency is no longer a fixed 4 regardless of batch size (Milestone 2),
  and confirm the initiating request does not block for the batch's full
  duration (Milestone 3) — both re-verified here at real 40-resume scale,
  not just at the smaller scale each milestone originally tested.

**Exit criteria:** Both runs completed, results and timing evidence written
into this milestone's `MILESTONE_LOG.md` entry, stated time budget is a real
measured number, and the outage run's output was manually inspected to
confirm no score-like number appears anywhere in it.

---

## Milestone 9 — Frontend logic wiring (structural, unstyled)

**Goal:** All backend changes from Milestones 1–4 are actually reachable and
usable from the browser — progress bar, distinct failure banner, past-runs
browser, corrected navigation — using minimum new HTML structure, explicitly
unstyled per `REBUILD_PROMPT.md` Section 1.

**Inputs needed:** All prior milestones' API surface.

**Implementation scope (explicitly temporary/unstyled, stated again here per
Section 1's requirement):**
- A real `<progress>` element or an unstyled `<div>` bar, driven by
  Milestone 3's polling response — replaces the current static status
  string.
- A distinct, plainly-marked banner element for the Milestone 1 batch-level
  "N/M resumes failed AI extraction" warning — basic HTML, no visual design
  work, just structurally present and correctly wired.
- A "Past Runs" list/button wired to Milestone 4's `/api/runs`, rendering
  through the same candidate-card rendering function already used for live
  results (no second implementation).
- Milestone 5's navigation fix (already implemented in its own milestone,
  confirmed wired here as part of the whole-app pass).
- No color, layout, or component work — this explicitly waits for the later
  UI/UX phase (Section 6 of `REBUILD_PROMPT.md`, out of scope for this
  document).

**Not included:** anything visual. If a reviewer looks at this milestone's
output and it looks plain/basic, that is correct and expected, not a
shortfall — restated from Section 1 so it isn't mistaken for unfinished work
later.

**Tests required:**
- Flask test client: `GET /`, `GET /candidate`, `GET /runs`-equivalent view
  all return 200 with the new elements present in the rendered HTML.
- JS syntax check (`node --check` on extracted `<script>` blocks, matching
  the existing verification pattern from `SESSION_HANDOFF.md`).
- One real click-through covering: upload → progress bar visibly updates →
  results appear progressively → a deliberate-failure run shows the banner
  → past runs list shows the run → reopening it renders correctly.

**Exit criteria:** All tests pass, click-through completed and confirmed
working, no visual/CSS changes present in the diff for this milestone
(verified by reviewing the diff itself, not just describing it).

---

## Milestone 10 — Full regression + Definition of Done sign-off

**Goal:** Every item in `REBUILD_PROMPT.md` Section 2 has a corresponding
passing test (not just "no longer reproduces manually"), and Section 5's
full checklist is verifiably true.

**Inputs needed:** Everything above.

**Implementation scope:** No new features — this is a verification pass.
Cross-reference each of Section 2's 8 numbered items against the specific
test(s) that now cover it (a table, written into this milestone's
`MILESTONE_LOG.md` entry, mapping bug → test file/name), so a future session
can confirm coverage exists without re-reading every test file.

**Tests required:** The full suite, run together: unit + integration +
LLM-pipeline-specific + the Milestone 8 load/outage evidence + Milestone 7's
security/dependency/lint results — all green in one sitting, with the
combined run's output retained as this milestone's evidence.

**Exit criteria (verbatim from `REBUILD_PROMPT.md` Section 5, each checked
individually):**
1. 40+ real resumes, end to end, within the Milestone 8 stated time budget,
   visible progress throughout — ✅/❌, evidence linked.
2. Simulated full outage produces a clearly labeled, non-zero-looking
   failure state — ✅/❌, evidence linked.
3. Fixture accuracy suite passes the Milestone 6 stated bar — ✅/❌.
4. Every Section 2 bug has a named passing regression test — ✅/❌, table
   included.
5. Full suite green, with a stated summary of what each test category
   covers — ✅/❌.

Only once all five are individually confirmed does this document consider
the backend/frontend-logic rebuild complete and the UI/UX phase (Section 6,
separately scoped later) eligible to start.

---

## What is explicitly NOT part of this plan

- Any visual/CSS/layout/component work (Section 1 and Section 6 of
  `REBUILD_PROMPT.md` — deferred to a separately-scoped later phase).
- Multi-user auth/accounts (unchanged from `WEB_APP_PLAN.md` Section 6).
- A move away from the free-tier host constraint — if the eventual free
  host chosen turns out not to support even ephemeral SQLite well, that's a
  Milestone 4 follow-up, not a reason to add paid infrastructure.
- Solving Render's (or whichever free host's) disk persistence guarantee at
  the infrastructure level — documented as a known, accepted limitation
  with an export-based mitigation, not engineered around with paid add-ons
  the user has said they can't use.
