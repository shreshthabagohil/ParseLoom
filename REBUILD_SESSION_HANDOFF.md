# REBUILD_SESSION_HANDOFF.md — paste this whole file as your first message in a new session

Written 2026-07-21, end of the session that closed Milestones 5, 5.5, and 6.
This is a handoff document for the **from-scratch rebuild** effort (not
the earlier pre-rebuild hackathon build — ignore `HANDOFF_PROMPT.md` and
`SESSION_HANDOFF.md` at the repo root, those are stale artifacts from a
prior phase of this project and are unrelated to the process described
here).

---

## 1. How this project works — read this before doing anything else

This is a disciplined, milestone-by-milestone rebuild governed by
`REBUILD_PROMPT.md`. The process rules in it are not optional framing —
they are the actual operating procedure for every session, including
this one:

1. **Read five files first, in order, before touching anything:**
   `PROJECT_CONTEXT.md`, `DESIGN_DECISIONS.md`, `WEB_APP_PLAN.md`,
   `SESSION_HANDOFF.md`, `RELIABILITY_SCALE_ANALYSIS.md`. These document
   the architecture, prior design decisions, and — critically —
   confirmed, previously-diagnosed bugs that must be designed around,
   never rediscovered from scratch. `RELIABILITY_SCALE_ANALYSIS.md` is
   explicitly called out as the most important of the five.
2. **Also read, every session, regardless of which milestone is
   active:** `REBUILD_PLAN.md` (the full milestone plan, now Milestones
   0–10 plus two mid-stream additions — Excel export between 3 and 4,
   and Milestone 5.5 between 5 and 6) and `MILESTONE_LOG.md` in full
   (append-only history of what actually happened on every milestone
   closed so far — problems hit, root causes, exact fixes, recurring-risk
   notes). This handoff file is a *supplement* to those two, not a
   replacement — they have far more detail than fits here.
3. **Plan before code.** Nothing gets implemented without a milestone
   plan stating goal, inputs, scope (including explicit non-scope),
   required tests, and exit criteria, per `REBUILD_PROMPT.md` Section 3.
   This applies even to mid-stream, user-requested additions — Milestone
   5.5 was written into `REBUILD_PLAN.md` in full before any code was
   touched, same discipline as every numbered milestone.
4. **`MILESTONE_LOG.md` is append-only, forever.** A new entry is
   written only once every test required to close that milestone
   actually passes — never as a draft, never before. If a milestone took
   multiple attempts, the entry documents the whole arc (what broke,
   root cause, exact fix), not just the clean end state. Never delete,
   rewrite, or summarize away a previous entry.
5. **No new scoring/parsing/export logic in the web layer, ever**
   (`WEB_APP_PLAN.md` Section 6) — `app.py` stays a thin wrapper over
   shared `src/` logic that `main.py` (the CLI) also uses. Confirmed
   again this session: the shortlist score-floor fix (Milestone 5.5)
   went into `src/matching/shortlist.py`, not `app.py`, specifically so
   `main.py`'s CLI output gets the same fix automatically.
6. **Long-term solutions only**, not quick patches — this was an
   explicit standing instruction from the user early in the rebuild and
   has held for every milestone since, restated again this session before
   Milestone 5.5's implementation.
7. **Security discipline, established and must continue:** never leak
   raw exceptions/stack traces/server file paths to the client (log real
   detail server-side, return a generic message); PII (email/phone)
   redacted before any LLM call; prompt-injection resistance in the
   extraction system prompt; `secure_filename()` on all client-supplied
   filenames; secrets never reach logs/errors/the browser; dependency
   scanning via `pip-audit`. Also standing as of Milestone 4/5.5: the
   original uploaded PDF is deleted immediately after each job finishes —
   confirmed again this session (user explicitly declined to reverse this
   for the sake of an Excel "view resume" link) as a decision that stays,
   not something to relitigate casually.
8. **Real (non-mocked) verification is expected, not optional, for
   anything load-bearing.** The user explicitly approved real Groq/Gemini
   API spend for testing ("Real calls are fine"). Multiple real bugs in
   this project have only ever been caught by an actual live-server,
   real-HTTP, real-API-call test — never by the mocked test suite alone.
   Do not treat "all mocked tests pass" as sufficient evidence that a
   feature works; run it for real too before calling a milestone done.
   This session specifically needed a **real browser** (tab-close/focus
   behavior, an incognito-window test with no shared `localStorage`) —
   neither is verifiable by `pytest` alone; both were confirmed by the
   user directly, with a screenshot for the incognito check.
9. **This is Cowork mode** (Claude Agent SDK / Claude Code under the
   hood, but referred to to the user as Cowork, not Claude Code). Shell
   commands run in an isolated Linux sandbox; the project folder is
   mounted into it. **Sandbox quirks confirmed across sessions:**
   - The mounted project folder is a FUSE-backed sync mount back to the
     user's actual machine — real implications for anything doing
     local-disk locking/mmap (see `MILESTONE_LOG.md`'s Milestone 4 entry,
     "Bug 3": SQLite WAL mode doesn't reliably work directly inside this
     mount).
   - Background processes (e.g. a `flask run` dev server started with
     `&`) do **not** survive between separate bash tool calls in this
     sandbox — each call is an independent shell. To do a live-server
     end-to-end test *from inside the sandbox*, start the server, run all
     `curl` commands, and kill it, all inside **one** bash call (max
     45s timeout per call) — or, as this session did instead, hand the
     user exact steps to run the live server themselves and report back.
   - This sandbox's `.venv` (created on the user's Mac) does not resolve
     here — `.venv/bin/python3` doesn't exist in this Linux environment.
     Confirmed again this session: install directly against this
     sandbox's system Python 3.11 via
     `pip install -r requirements.txt --break-system-packages` (plus
     `pytest`) instead of trying to activate `.venv`. This is a
     sandbox-only workaround; the user's own Mac `.venv` is a separate,
     real environment that needs its own `pip install -r requirements.txt`
     when a new dependency is added (this bit the user directly this
     session: `openpyxl` was already in `requirements.txt` from an
     earlier session but their local `.venv` had never picked it up).
   - `node --check /dev/stdin` is unreliable in this sandbox specifically
     (`ENOENT` against a pipe fd) — use a real temp file instead
     (`tests/test_frontend_js_regression.py` does this).

---

## 2. What this rebuild covers (and what it deliberately does not)

**In scope:** the entire backend (`src/`, `app.py`, `main.py`) and the
entire frontend *logic* (JS wiring, state, API calls, routing,
error/loading states) — rebuilt cleanly with the accumulated knowledge of
what broke in the pre-rebuild version and why (see
`RELIABILITY_SCALE_ANALYSIS.md`).

**Explicitly out of scope for now:** visual UI/UX redesign. The existing
CSS/layout/palette/Fable-authored markup stays untouched. Where new logic
needs new structural HTML (e.g. a progress bar, a Past Runs list, a
"Slots unfilled" summary field), add the minimum markup needed and leave
it visually unstyled/basic — a separately-scoped later phase handles
making the whole UI polished, per `REBUILD_PROMPT.md` Section 6 (do not
start that phase early; it needs its own kickoff, including asking the
user to re-share a palette reference image that does not carry over
automatically between sessions).

---

## 3. Milestone status

| # | Name | Status |
|---|------|--------|
| 0 | Eliminate `main.py`/`app.py` `parse_one_resume` duplication | ✅ Done |
| 1 | Explicit, distinct LLM-failure state (not silently disguised as bad data) | ✅ Done |
| 2 | Rate-limit-aware concurrency, dual-provider (Groq→Gemini) failover, content-hash caching | ✅ Done |
| 3 | Async job architecture with progressive/streaming results (background threads + polling) | ✅ Done |
| 4 | Persistent run history (SQLite, per-client-scoped, concurrency-safe) — *plus the Excel export feature, added mid-stream* | ✅ Done |
| 5 | Cross-tab "Back to results" fix | ✅ Done |
| 5.5 | Shortlist score floor + shareable candidate detail links — *added mid-stream at the user's request* | ✅ Done |
| 6 | Fixture-based extraction accuracy suite | ✅ Done (this session) |
| 7 | Security, dependency, and code-health pass | ⬜ Not started — **next up**. Partially pulled forward already — remaining scope not yet confirmed against `REBUILD_PLAN.md`'s exact Milestone 7 text |
| 8 | Full 40-resume load test + simulated full-provider-outage test | ⬜ Not started |
| 9 | Frontend logic wiring (structural, unstyled) | ⬜ Not started |
| 10 | Full regression + Definition of Done sign-off | ⬜ Not started |

Read the exact scope/exit-criteria for each pending milestone directly
from `REBUILD_PLAN.md` before starting it — don't rely on the one-line
summaries above.

Two unscoped features have been added mid-stream so far, both with their
own `MILESTONE_LOG.md` entries and both fully done/tested: **Excel export**
(between Milestones 3 and 4) and **Milestone 5.5** (shortlist score floor +
shareable detail links, between Milestones 5 and 6). If a third
user-requested addition comes up before Milestone 6 starts, follow the
same pattern: write it into `REBUILD_PLAN.md` as a numbered/lettered
addition with full goal/scope/tests/exit-criteria before touching code,
implement, verify for real, then log it.

---

## 4. What actually happened this session (Milestones 5, 5.5, and 6) — read the full entries in `MILESTONE_LOG.md`, this is a compressed pointer

**Milestone 5** turned out to already be implemented in code
(`templates/candidate.html`'s `window.close()` + fallback), left over from
the pre-rebuild session and never logged or re-verified under this
project's discipline. Reviewed it line-by-line against `REBUILD_PLAN.md`'s
spec, confirmed it was correct as written (no code changes needed for
Milestone 5 itself), and — while reviewing that exact code path — found a
real, separate bug: reopening a historical run via "Past Runs" never wrote
its payload to `localStorage['parseloom_last_run']`, so "View full
details" from a reopened run showed stale/missing data. Fixed, with a new
`tests/test_frontend_js_regression.py` (JS syntax check for both templates
via `node --check`, plus a regression test asserting the fix's exact
ordering). The user then did the real browser click-through themselves and
confirmed "Back to result works."

**Milestone 5.5** (new, added this session at the user's request after
they spotted two real problems in a live run):

1. A candidate with **zero skill overlap** with the JD was appearing in
   the Shortlist just because a slot was open — `build_shortlist()` had no
   minimum-score floor. Fixed in `src/matching/shortlist.py`: score ≤ 0
   candidates now always route to Reserve (never hidden, just never fill a
   slot), `summary.slots_unfilled` reports the honest gap. Documented in
   `PROJECT_CONTEXT.md` Section 6.
2. The Excel export's candidate rows had no way to open a specific
   candidate's detail page. Gave `/candidate` a real server-side data path
   (`?job_id=` or `?run_id=&client_id=`, additive — the original
   same-tab `localStorage` path is unchanged) and added a "Details Link"
   column to the Shortlist/Reserve sheets, wired through
   `app.py`'s two export routes. The original PDF stays deleted per the
   standing PII policy — confirmed with the user this was the intended
   scope (link to structured detail, not the raw file), not a shortfall.

Both fixes were verified for real by the user, not just by `pytest`:
confirmed a zero-overlap candidate landed in Reserve on a real run,
confirmed the Excel export's per-candidate data and "Details Link" column,
and — critically — opened a Details Link in a **fresh incognito window**
(screenshot provided) with no shared `localStorage`, confirming the link is
genuinely shareable and not silently dependent on the originating tab.

**Milestone 6** built `tests/test_extraction_accuracy.py`: 8 fixtures (7
real resumes from `data/real_resumes/`, 1 synthetic percentage-CGPA
resume — `tests/fixtures/accuracy_fixtures.json`, expected values
recorded by directly reading each PDF, not guessed), run for real against
Groq. A local, no-API-cost script reused `pdf_reader.py`'s own
column-detection logic to confirm fixture selection (31/54 real resumes
two-column — matched `PROJECT_CONTEXT.md`'s already-documented number
exactly). Also added: the two existing corrupted/empty-file fixtures run
through the full pipeline (no API cost, confirm graceful `Failed`, no
crash), and a **new** prompt-injection PDF fixture
(`tests/fixtures/mock_prompt_injection.pdf`) run through the full
pipeline — extends the pre-existing `test_prompt_injection_resistance.py`
(which only tested the LLM call in isolation on a hand-written string)
into a real, full-pipeline, real-PDF-file proof of the same property. The
whole file is `@pytest.mark.slow` (new `pytest.ini`, `addopts = -m "not
slow"`) — excluded from the default fast run, invoked explicitly via
`pytest tests/test_extraction_accuracy.py -m slow`. One real bug was
found in the *test* itself (an ALL-CAPS name assertion using exact `==`
instead of the case-insensitive match the main suite already used — not
a product regression), fixed, re-verified. Real result: **100% name
accuracy, 100% CGPA accuracy, 100% skill recall** on the first real run
against the stated 85%/90%/75% bar — see
`tests/fixtures/accuracy_report.md`.

The full `MILESTONE_LOG.md` entries for all three have considerably more
detail (exact bugs, exact fixes, exact test names) — read them, don't
rely on this summary alone.

---

## 5. Current state of the codebase (as of end of this session)

- **143/143 tests passing**, full fast suite (`pytest tests/`), verified
  3x consecutively (up from 124 at the start of this session — 19 new
  tests across Milestones 5 and 5.5, plus 4 new slow-marked tests in
  Milestone 6 that don't count toward the fast-suite number since they're
  deselected by default).
- **4/4 slow-marked tests passing** (`pytest tests/test_extraction_accuracy.py
  -m slow`), real Groq calls, run twice this session for consistency.
- `pip-audit` was clean as of the security-audit-pass entry earlier in
  `MILESTONE_LOG.md`; **not re-run this session** (no new runtime
  dependencies were added — `pytest.ini` and the new test/fixture files
  don't add any). This is genuinely due at the start of Milestone 7 —
  it's explicitly in that milestone's scope, not optional prep.
- Real Groq API key is present in `.env` and was exercised for real this
  session (Milestone 6's accuracy suite + prompt-injection PDF test — 9
  real LLM calls total, all successful).
- The user's local `.venv` did not have `openpyxl` installed even though
  it's been in `requirements.txt` since the Milestone 4 session — a real
  `pip install -r requirements.txt` in their own terminal fixed it. Worth
  a reminder at the start of any session that requires the user to run
  the live server locally: their `.venv` can drift behind
  `requirements.txt` silently.
- `instance/` (the SQLite DB directory) is gitignored — never committed,
  contains real candidates' extracted PII, same reasoning as
  `data/real_resumes/`.
- The repo is intentionally **public** on GitHub — confirmed explicitly
  by the user earlier in the rebuild, documented as an addendum in
  `MILESTONE_LOG.md`.
- Real sample PDF fixtures exist at `data/random_mocks/*.pdf` — useful
  for quick live-server smoke tests without needing the user's own
  resume uploads.
- Nothing from this session has been committed to git yet — same
  from-the-user's-own-terminal git workflow used throughout this rebuild
  applies (`git add -A && git commit -m "..." && git push`), not from an
  AI sandbox.

---

## 6. Immediate next step

Start **Milestone 7 — Security, dependency, and code-health pass**
(`REBUILD_PLAN.md`, the section immediately after Milestone 6, for its
exact scope/exit criteria). Read it in full before writing any code —
don't re-derive the approach from a one-line summary.

Concretely, Milestone 7 needs, per its own listed scope: automated
regression tests for the three `PROJECT_CONTEXT.md` Section 11.7 fixes
(API-key-in-exception scrubbing, multi-occurrence PII redaction,
prompt-injection resistance — the last one is already covered, cross-
reference rather than duplicate, per Milestone 7's own text, since
Milestone 6 added both a raw-string test and a full-PDF-pipeline test for
it), upload-validation tests (oversized file, wrong extension, over-cap
file count, fake-`.pdf`-extension-real-non-PDF-bytes), an error-response
test (no stack trace/path leak on a forced unhandled exception), a fresh
`pip-audit` run (genuinely not done yet, not just stale), `ruff` lint,
and a dead-code check. Before starting, per the standing process rule:
confirm this still matches current reality — Milestone 7 was scoped
before Milestones 5, 5.5, and 6 existed, so re-read it fresh rather than
assuming nothing shifted (in particular, `pytest.ini`'s new `slow` marker
and Milestone 5.5's new `src/output/xlsx_export.py`/`app.py` surface
didn't exist when Milestone 7 was originally scoped — check whether
either needs its own security/lint attention as part of this pass, since
Milestone 7's own framing is "the whole rebuilt surface, not a single
component").
