# ParseLoom Web App — Reliability & Scale Analysis + Plan

Written 2026-07-20, based on code inspection (`app.py`, `src/ai_client.py`,
`src/extraction/llm_extract.py`, `src/extraction/pdf_reader.py`,
`src/matching/scorer.py`) and a live terminal log from a fresh run today.
No code has been changed as part of this document — analysis and plan only.

---

## 1. Confirmed root causes

### 1.1 Silent full-batch LLM failure disguised as bad data — CONFIRMED

Traced end to end in code:

- `llm_extract.py` raises `LLMError` when the LLM call fails for any reason
  (rate limit, bad key, unparseable JSON, timeout).
- `app.py::parse_one_resume()` catches that `LLMError`, sets
  `parse_status = "Partial"`, and returns the resume with `skills=[]`,
  `full_name=None`, `projects=[]`, `experience=[]` — silently. No distinct
  signal that the *call itself* failed, as opposed to the resume genuinely
  having thin content.
- `scorer.py::score_candidate()` then computes `required_avg=0`,
  `preferred_avg=0` → `skill_subscore=0`; `_completeness_fraction()` is
  `0/4` (no name, no CGPA, no skills, no projects/experience) →
  `final_score = round(0 * (0.5 + 0*0.5), 1) = 0.0`, exactly.

This is exactly what was seen earlier today: three different resumes all
showed "Name not extracted," score `0`, and an *identical* missing-skills
list. That's not three bad resumes — it's the same LLM failure happening
three times, and the UI currently cannot tell the difference between
"the AI provider is down/rate-limited right now" and "these resumes are
genuinely low-signal." Both render as a wall of `0`s.

**Why this matters for judging:** if a judge's live upload happens to land
during a rate-limited moment, they'll see the engine apparently fail on
every resume, with nothing in the UI explaining that it's a transient
provider issue rather than a broken scoring engine.

### 1.2 Slow, unpredictable response time — CONFIRMED slow, exact cause not yet isolated

From today's log:

```
POST /api/run  11:16:27  400   (rejected fast — likely missing JD/files)
POST /api/run  11:17:51  200   (succeeded)
```

Independent of exactly when the second request started, this matches your
report of "more than a minute for 4 resumes." Structurally, each resume's
path is:

1. Local PDF text extraction (fast, in-process).
2. **Conditional** OCR fallback (`pytesseract` at 300 DPI) if standard
   extraction yields under ~50 words — CPU-bound, can be several seconds
   per page.
3. **One** LLM call via `_post_with_retry`: up to 5 attempts, 30s timeout
   each, exponential backoff between attempts (1/2/4/8s, capped at 15s).

Concurrency is hard-capped at 4 worker threads regardless of batch size
(deliberate, to avoid bursting the provider's per-minute rate limit — see
`app.py` comment).

**The real gap:** there is currently zero timing instrumentation anywhere
in this pipeline. Nothing logs how long PDF extraction, OCR, or the LLM
call itself took per resume. So right now it's impossible to say from logs
alone whether the >60s came from real LLM generation latency, OCR running
on scanned resumes, retry/backoff sleeps from transient errors, or several
of these stacking on different resumes within the same 4-wide batch. This
needs to be measured, not guessed at.

### 1.3 Scaling: 40 resumes will not scale safely from today's 4

- Concurrency is fixed at 4 workers no matter the batch size. 40 resumes
  means **10 sequential rounds of 4**, not 40 in parallel. If 4 resumes
  already take over a minute, 40 will realistically take on the order of
  10+ minutes end to end — worse if any round hits retries.
- `/api/run` is fully synchronous: the whole HTTP request blocks until
  every resume in the batch finishes. The browser tab just sits on a
  static status string ("Parsing N resumes... expect a few seconds each")
  that becomes actively misleading once real time is 10x that. No
  progress bar, no per-file status, no partial results, no cancel button.
- `MAX_FILES_PER_REQUEST = 20` caps a single request at 20 files, so a
  real 40-resume run can't even be submitted as one batch today — it
  would need two manual uploads, with no batching/chunking UI to make
  that transparent. You're right that 20 isn't a helpful number for a
  40-resume target.
- If/when this deploys to Render (per your commit history), most hosting
  platforms' reverse proxies enforce a request timeout in the 30–100s
  range by default. A synchronous request that takes minutes will
  **hard-timeout in production** even if it behaves locally. This is a
  deployment blocker, not just local UX polish.

### 1.4 "Back to results" navigates the wrong tab — my earlier fix was incomplete

The earlier fix (switching `sessionStorage` → `localStorage`) solved "the
detail tab can't read the run data," and as a side effect made navigating
`/` *inside that same tab* show the same results again. But that's not
what you're asking for: you want "Back to results" to return to the
**original tab** — the one still showing the live upload form and
in-place results — not re-render an equivalent page inside the detail tab.
Those are different outcomes even though both superficially "show
results."

Since the detail tab is opened via a same-origin `target="_blank"` link
with no `rel="noopener"`, `window.opener` is preserved, so `window.close()`
should return the user directly to the original tab. Needs a fallback
(navigate to `/`, which still restores via `localStorage`) for the rare
case where the tab wasn't script-openable — e.g. the user manually opened
it in a new window in a way that severed the opener reference.

### 1.5 "Data seems incorrect" — currently no way to independently verify

There's no fixture/golden-file test comparing a known resume's
expected extracted fields (name, skills, CGPA, etc.) against what the LLM
actually returns. The existing 29 pytest tests only cover
`scorer.py` / `grade_normalizer.py` / `skill_matcher.py` pure math — never
the extraction call itself or its accuracy against real resumes.

Given 1.1 above, "incorrect data" right now could mean two very different
things that currently look identical in the UI:

- (a) the LLM extraction genuinely ran and got some field wrong — a real
  accuracy issue, or
- (b) the LLM call silently failed and the UI is showing the
  empty-fallback state, which isn't a data-quality bug at all — it's an
  error being displayed as if it were data.

These can't be meaningfully told apart until 1.1 is fixed. Once failures
are surfaced explicitly, it becomes possible to re-diagnose whether
remaining "wrong-looking" results are real extraction mistakes on resumes
that *did* complete successfully.

---

## 2. Plan

### Phase 1 — Make failures visible (do this first; cheap, highest value)

- Add a distinct status (e.g. `parse_status = "LLMFailed"` or a separate
  boolean flag) instead of folding LLM-call failures into the existing
  `"Partial"` status, which currently conflates "genuinely messy resume,
  some fields missing" with "the LLM call itself errored out." Give it a
  visually distinct badge in the UI — e.g. red "AI extraction failed" vs.
  amber "Partial parse" — so a wall of failures cannot be mistaken for a
  wall of bad resumes.
- In `/api/run`, count how many resumes in a batch hit this new failure
  state. If it crosses a threshold (e.g. more than half the batch),
  return a distinct top-level warning in the JSON response — something
  like "N/M resumes failed AI extraction — this usually means the AI
  provider is rate-limited or misconfigured, not that these resumes are
  low quality" — and render it prominently above the results, not buried
  inside individual cards.
- Add timing instrumentation: wrap PDF extraction, OCR (when triggered),
  and the LLM call each in a timer; log `resume_file, stage, duration_ms`
  at INFO level. This directly answers "where is the time going" on the
  very next run instead of relying on guesswork.

### Phase 2 — Fix the two concrete UX bugs you flagged

- **Back to results:** replace the plain `<a href="/">` nav link in
  `candidate.html` with a click handler that calls `window.close()`,
  falling back to `location.href = '/'` after a short delay if the window
  didn't actually close (not opener-owned).
- **File cap:** raise `MAX_FILES_PER_REQUEST` from 20 to match your real
  target (e.g. 50), *and* add client-side chunking so uploading 40 files
  transparently fires multiple sequential batches with one combined
  progress view — rather than making you manually split uploads into two
  runs.

### Phase 3 — Real scaling changes for 40+ resumes

Move off a fully synchronous request/response for large batches. Two
shapes, pick based on runway before the next demo:

- **Minimal:** `/api/run` kicks off a background job (thread) and returns
  a `job_id` immediately. A polled `/api/run/<job_id>/status` endpoint
  (every 1–2s) returns progress (`X/N done`) and, once finished, the same
  payload shape as today. Frontend renders a real progress bar and
  results stream in as they complete.
- **More robust** (if there's time): a lightweight in-process task queue
  (a `queue.Queue` plus a background worker pool, no external
  infrastructure) behind the same polling contract above — avoids a full
  Celery/Redis re-architecture for something this scale.

Also:

- **Re-tune concurrency.** The current 4-worker cap was a safety choice,
  not a measured one. Check the actual published rate limit for
  `llama-3.3-70b-versatile` on your Groq tier (requests/minute) and set
  `max_workers` to the largest value that stays safely under it. This
  alone could meaningfully cut wall-clock time with no other changes.
- **Cache by content hash.** A short-lived in-memory cache keyed by
  SHA-256 of the uploaded file bytes means re-running the same resume
  during testing/demo doesn't re-spend an LLM call — pure win for
  iteration speed and quota conservation, no correctness risk.

### Phase 4 — Data-quality verification (after Phase 1 makes failures visible)

- Build a small fixture set: 5–10 resumes with manually-verified expected
  values (name, skills, CGPA) checked into `tests/fixtures/`. Add an
  integration test (marked slow/optional, kept out of the fast pytest
  suite) that runs real extraction against them and diffs against
  expected values — so "is the data actually correct" becomes something
  checkable on demand instead of eyeballed from screenshots.
- Once Phase 1 exists, re-run today's exact batch and see whether the
  "incorrect" results were failures (now visibly labeled, not silent) or
  genuine extraction mistakes on resumes that completed successfully —
  worth re-diagnosing with fresh eyes once the two are no longer
  conflated in the UI.

---

## 3. Workflow discipline to carry forward

- Any LLM-call-adjacent change should be exercised against **both** a
  rate-limited scenario and a fully-working one before being called done
  — 1.1 exists precisely because the "everything failed" path was only
  ever reasoned about in code comments, never actually driven through the
  UI end to end.
- Any change to concurrency/timeouts/retries should log a
  timestamp + duration, not just pass/fail, so the next "why is this
  slow" question has data instead of requiring re-diagnosis from scratch.
- Treat `MAX_FILES_PER_REQUEST` and `max_workers` as tunable, documented
  constants with a one-line rationale each (already partly true) — but
  revisit the actual numbers now that "up to 40 resumes" is a real
  target, not a hypothetical one.
