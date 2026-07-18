# PROJECT_CONTEXT.md — InternLoom Resume Shortlisting Engine (AI Dev Track)

This is the single source of truth. Any AI tool you switch to reads this
file FIRST, before you explain anything in chat. Update it the moment a
decision changes — not retroactively.

Last updated: 2026-07-18, by Claude

**Canonical shared folder:** `/Users/shreshtha/Cllg hackathon/ParseLoom`
— both Claude (Cowork) and Antigravity work directly in this exact
folder from now on. No more zip transfers between them. If you're a
fresh AI session reading this, confirm you were pointed at this path,
not a stray copy elsewhere.

## 0. The decision that got us here

Three tracks were offered: Web Dev (backend matching API), AI Dev (resume
shortlisting engine), App Dev (Flutter swipe app). We chose **AI Dev**.
Reasoning, for anyone picking this up cold:

- The hardest sub-problems in this track (multi-column PDF layout,
  extracting skills from unstructured text) have LLM-delegated solutions
  the problem statement itself sanctions. That plays directly to the
  user's strength (prompt engineering) rather than deep systems/CS
  fundamentals they're still building.
- Web Dev explicitly requires self-implemented auth ("do not use
  third-party OAuth — implement it yourself") which conflicts with the
  Supabase-based prep from the night before, and its hardest parts
  (concurrent-apply race conditions, state-machine correctness) are hard
  because of the reasoning required, not fixable by AI-generated code the
  user can't fully verify.
- App Dev requires Flutter/Dart (zero prior prep, zero user familiarity)
  plus a working Android emulator — highest environment risk.
- The AI Dev JD dataset is literally sourced for Relyntis (the agentic-AI
  company flagged in prep-night research) — direct alignment with who's
  actually hiring.
- User's Python level: basics. Architecture below is deliberately built
  to minimize custom algorithmic Python and maximize LLM-delegated
  reasoning wrapped in short, plainly-written glue code, so every line
  can be explained live to a judge.

## 1. Problem recap

Build a CLI engine that: accepts a folder of real, messy PDF resumes +
a Job Description (one of 5 known roles, or an arbitrary 6th), and
produces a ranked, scored, explainable shortlist with parse-quality
transparency. Two stages: extraction (PDF → structured data) and
matching (structured data → score against JD). Stage 1 is the harder,
more heavily-weighted stage (20 of 100 core marks on parsing quality
alone).

Real dataset (real messy resumes) is only available at 10:00 AM via a
Google Drive link. Everything in this plan is built and tested against
synthetic edge-case resumes tonight/beforehand, so 10:00–11:00 tomorrow
is "point at real data and fix what breaks," not "start from zero."

## 2. Tech stack (locked — do not re-litigate mid-build)

- Language: Python 3.11+ (required by the problem statement)
- PDF extraction + rasterization: **PyMuPDF (fitz) only**. One library
  does both text+bounding-box extraction and page-to-image rendering for
  OCR, which keeps the dependency surface small and the code simple.
  (pdfplumber is allowed but deliberately not used — no reason to learn
  two libraries under time pressure when one covers both needs.)
- OCR: pytesseract + Pillow. Requires the `tesseract-ocr` system binary
  installed separately (not pip-installable) — **verify `tesseract
  --version` works during the 9:00–9:30 registration window**, this is
  the one real environment-setup risk in this stack.
- LLM calls: plain `requests` against provider REST APIs (OpenAI /
  Anthropic / Gemini), same provider-agnostic pattern as the Next.js
  boilerplate from the night before, ported to Python. No heavy SDKs —
  fewer install failure points, one function (`call_llm`) to understand.
- Data models: stdlib `dataclasses`, not pydantic. No validation magic
  to explain under pressure — just plain fields, `dataclasses.asdict()`
  for JSON output.
- CLI: stdlib `argparse`. No click dependency.
- Output: JSON (primary) + optional CSV.

## 3. Folder structure

```
internloom-resume-engine/
  main.py                    CLI entrypoint
  requirements.txt
  README.md
  DESIGN_DECISIONS.md         answers the 4 Tricky Parts (submission-required)
  AI_USAGE_LOG.md              max 200 words (submission-required)
  PROJECT_CONTEXT.md, TASKS.md, HANDOFF_PROMPT.md   (this continuity system)
  src/
    extraction/
      pdf_reader.py           PyMuPDF text + bounding-box extraction, column split
      ocr_fallback.py         rasterize + pytesseract when text yield is low
      grade_normalizer.py     CGPA/percentage/GPA-4 -> unified 10-pt scale
      llm_extract.py          one LLM call -> structured resume JSON
      skill_vocab.py          curated skill vocabulary + synonym map
    matching/
      skill_matcher.py        exact/synonym/partial/implicit classification
      scorer.py                weighted score + confidence + reasoning bullets
      shortlist.py              slot-aware shortlist / reserve / needs-review split
    models.py                  dataclasses: ParsedResume, JobDescription, ScoreResult
    jd_loader.py                loads the 5 known JDs, or arbitrary structured/free-text JD
    ai_client.py                 provider-agnostic call_llm(), ported from the TS boilerplate
    report.py                    writes shortlist JSON, parse quality report, summary lines
  data/
    jds.json                     the 5 known JDs, hardcoded from the problem statement
    test_resumes/                 synthetic edge-case PDFs built tonight, for pre-testing
  output/
    sample_output.json            generated after a real run
    parse_quality_report.md        generated after a real run
```

## 4. Data models

```python
@dataclass
class ParsedResume:
    file_name: str
    raw_text: str
    parse_method: str        # "text" | "ocr" | "failed"
    parse_status: str        # "Clean" | "Partial" | "Failed"
    parse_notes: list[str]   # human-readable notes, shown in parse quality report
    full_name: str | None
    email: str | None
    phone: str | None
    college: str | None
    degree_branch: str | None
    graduation_year: int | None
    cgpa_10pt: float | None
    cgpa_source_format: str | None   # "cgpa10" | "percentage" | "gpa4" | "ambiguous"
    skills: list[str]
    projects: list[dict]      # [{title, description}]
    experience: list[dict]    # [{company, role, duration}]
    certifications: list[str]
    text_word_count: int

@dataclass
class JobDescription:
    role: str
    required_skills: list[str]
    preferred_skills: list[str]
    cgpa_min: float
    slots: int

@dataclass
class ScoreResult:
    candidate_file: str
    candidate_name: str | None
    score: float              # 0-100, None if parse_status == "Failed"
    confidence: str            # "High" | "Medium" | "Low" | "N/A"
    reasons: list[str]         # exactly 3 bullets
    parse_quality: str          # "Clean" | "Partial" | "Failed"
    below_cgpa_minimum: bool
```

## 5. The four Tricky Parts — design decisions (locked)

**Tricky Part 1 — Multi-column layout.** Use
`page.get_text("blocks")` to get text blocks with bounding boxes.
Compute the x-midpoint of each block; if blocks cluster into two clear
horizontal groups (roughly left-of-center / right-of-center with a gap
between), classify as two-column. Split into left/right groups by x0,
sort each group top-to-bottom by y0, concatenate left-column text then
right-column text. Known failure case: a full-width header/name banner
spanning both columns can get miscategorized into one column; true
3-column layouts aren't specifically handled and will approximate as
two.

**Tricky Part 2 — Scanned resume / OCR.** After standard text
extraction, count words. If word count < 50, treat as a scan candidate:
rasterize each page via `page.get_pixmap(dpi=300)`, run pytesseract on
the resulting image, replace raw_text with OCR output, set
`parse_method = "ocr"`. If OCR *also* yields < 50 words, set
`parse_status = "Failed"` with a clear note — no score is computed for
that candidate, only a flag and a human-review recommendation.

**Tricky Part 3 — Skill extraction from unstructured text.** Hybrid,
not either/or: (1) a curated vocabulary of skill terms + synonym map
covering every skill across the 5 known JDs, searched across the *full*
resume text (not just a "Skills" section) for fast, deterministic,
auditable matches; (2) one LLM call per resume, sent the full
(column-fixed, OCR-recovered-if-needed) text, asked to return structured
JSON — name, email, phone, college, degree, grad year, raw CGPA + scale
guess, skills, projects, experience, certifications. The LLM pass is
what actually extracts most of Stage 1's structured fields (name,
college, projects, etc.) — the vocabulary pass exists specifically to
give skill matches an auditable, non-LLM-dependent confidence signal.
What this misses: skills phrased in ways neither the vocabulary nor the
model recognizes (invented tool names, very obscure or brand-new tech).

**Tricky Part 4 — Parse quality gates confidence, always.** A `Clean`
parse can reach `High` confidence. A `Partial` parse is capped at
`Medium`, regardless of how strong the extracted data looks — this is
enforced as a hard rule in the scorer, not a suggestion. A `Failed`
parse produces no score at all: only a flag and a "recommend human
review" note. This logic lives in one place (`scorer.py`) so it can't be
silently bypassed by a code path that forgets to check it.

## 6. Scoring algorithm

1. **Skill match subscore (0–100):** each required skill classified
   exact/synonym (full credit, 1.0), partial (0.5), implicit (0.25), no
   match (0) — averaged → `required_score` (0–1). Same for preferred
   skills → `preferred_score` (0–1).
   `skill_subscore = required_score * 70 + preferred_score * 30`
2. **CGPA eligibility gate:** candidates below `jd.cgpa_min` are still
   scored and shown — never silently dropped — but flagged
   `below_cgpa_minimum = True` and routed to the Reserve list regardless
   of score. This is a defensible, documented eligibility rule, not a
   hidden exclusion.
3. **Signal-conflict adjustment (±5, documented, not hidden):** high
   CGPA + zero projects, or low CGPA + multiple deployed projects, or
   perfect skill match + non-CS degree — each produces a small,
   bounded score nudge *and*, more importantly, gets surfaced explicitly
   in the reasoning bullets. Explainability matters more here than the
   number.
4. **Completeness factor:** `final_score = skill_subscore * (0.5 + 0.5 *
   completeness_fraction)`, where completeness_fraction is the share of
   core fields (name, cgpa, skills, at least one project/experience)
   that weren't null. A 40%-complete resume is penalized meaningfully,
   never zeroed.
5. **Confidence:** derived from parse_status (hard cap per Tricky Part
   4) and how implicit-match-heavy the skill matches were.

## 7. Grade normalization

- Bare number 4–10, no unit → CGPA-10 as-is.
- Number with `%` → `cgpa = value / 9.5`.
- Number 0–4 explicitly labeled GPA, or context suggests 4-point scale →
  `cgpa = value * 2.5`.
- Bare number 0–4 with **no** label → genuinely ambiguous (could be low
  CGPA or GPA-4). Assume CGPA-10 as-is, state the assumption in
  `parse_notes`, and flag `cgpa_source_format = "ambiguous"` → this
  candidate cannot reach High confidence regardless of other signals.

## 8. JD loading (covers core requirement + Bonus C in one code path)

`jd_loader.load(input)` accepts three shapes and auto-detects which:
1. A known role name/ID → loaded from `data/jds.json` (the 5 hardcoded
   JDs from the problem statement).
2. Structured input (JSON with `required_skills`/`preferred_skills`/
   `cgpa_min`/`slots` keys) → used directly. This is how judges will
   most likely hand over a 6th JD.
3. Raw unstructured text (a pasted job posting) → routed through an LLM
   extraction prompt to pull the same fields. This *is* Bonus C, but
   building it as one flexible loader from the start means it's free —
   not a separate feature to bolt on later.

## 9. Output format (per JD)

```json
{
  "jd": "Frontend Developer",
  "summary": {
    "evaluated": 30,
    "shortlisted": 8,
    "score_cutoff_used": 62.4,
    "parse_failures": 1
  },
  "shortlist": [
    {"rank": 1, "file": "...", "name": "...", "score": 91.2,
     "confidence": "High", "parse_quality": "Clean",
     "reasons": ["...", "...", "..."]}
  ],
  "reserve": [ "...same shape, includes below-cutoff and below-cgpa-min candidates..." ],
  "needs_review": [ {"file": "...", "reason": "Failed parse: scanned image, OCR yielded 12 words"} ]
}
```

## 10. Environment variables

`AI_PROVIDER` (openai | anthropic | gemini), `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` / `GEMINI_API_KEY` — same pattern as the Next.js
boilerplate, values go in `.env`, never committed.

## 10.5 Human-in-the-loop (explicit design principle, a judge flagged this)

A judge specifically called this out, so it's documented as a named
principle, not left implicit: **the engine's job is to reliably sort the
easy majority and honestly flag the rest for a human — never to produce
a confident-looking number it can't actually back up.**

Concretely, three places in this system exist specifically to route
uncertainty to a human instead of hiding it:
1. A `Failed` parse produces **no score**, only a flag and an explicit
   "recommend human review" note (Section 5, Tricky Part 4).
2. A `Partial` parse is hard-capped at `Medium` confidence, no matter how
   strong the visible data looks (same rule).
3. An ambiguous CGPA scale assumption is stated outright in
   `parse_notes` rather than silently guessed (Section 7).

**Data minimization, added after a judge's note on security:** not
everything on a resume needs to leave the machine and go to a
third-party LLM API. Email and phone number are both reliably
extractable with plain regex — no semantic understanding required. We
extract them locally first (`src/extraction/pii_redact.py`), redact them
out of the text (`[EMAIL_REDACTED]`, `[PHONE_REDACTED]`), and only send
the redacted text to the LLM for the fields that actually need language
understanding (skills, projects, experience, degree/college). Contact
info is merged back into the final `ParsedResume` afterward. Tested
against both real resumes — catches Indian mobile formats and standard
emails correctly. This is a genuine security/privacy improvement, not
just a talking point: less real students' PII crosses the wire to
OpenAI/Anthropic/Gemini than a naive "send the whole resume" approach.

This is also the honest answer to "make sure accuracy is 99%": on real,
messy, unformatted PDFs, chasing a literal accuracy number is the wrong
target — the problem statement itself says there's no single correct
solution and explicitly penalizes systems that fake confidence on data
they can't actually handle. The right target is maximum accuracy on
what the engine *can* confidently read, paired with zero silent guessing
on what it can't. A judge reads "70% High confidence, 20% Medium, 10%
flagged for human review, all correctly labeled" as a stronger result
than a system that claims high confidence everywhere and is wrong some
of the time. Confidence and parse-quality flags are not hedging — they
are the actual deliverable.

## 11. Known issues / workarounds

- Fixed: Gemini occasionally returns 503 ("model overloaded"). Original
  retry logic only handled 429; now retries with exponential backoff on
  429/500/502/503/504 (`src/ai_client.py`, `_post_with_retry`).
- **CONFIRMED against the full real 54-PDF dataset (2026-07-18, Claude in
  Cowork).** `python main.py --resumes data/real_resumes --all-jds
  --output output` was run to completion (in practice, across many short
  invocations due to a sandbox exec-time limit, but using the exact same
  `parse_one_resume` / `score_candidate` / `build_shortlist` code paths
  main.py uses — see `scripts/incremental_parse.py` +
  `scripts/finalize_from_cache.py`, not part of the submission, just the
  harness used to drive main.py's logic within short calls). Real,
  verified results, read directly from `output/parse_quality_report.md`
  and `output/sample_output.json`:
  - **54/54 Clean, 0 Partial, 0 Failed.** `parse_method` is `"text"` for
    all 54 -- **no scanned resume exists in this real dataset**, so the
    OCR fallback path (`ocr_fallback.py`) still has NOT been exercised
    against a real scanned file. It only ran successfully in a synthetic
    test. Do not claim OCR is confirmed on real data.
  - **Column-split logic: CONFIRMED firing on real data.** Checked
    directly against all 54 PDFs (bypassing the LLM step): 31/54 had at
    least one page where `_column_aware_text` classified it as genuine
    two-column layout and split it. Text extraction quality on those
    files looked coherent, not interleaved/garbled.
  - **Partial skill matching: CONFIRMED, 114 real occurrences** across
    the 54 resumes x 5 JDs x skill-list combinations (e.g. `Next.js` /
    `TypeScript` credited as partial matches toward `React.js` /
    `JavaScript` JD requirements).
  - **Implicit skill matching: CONFIRMED, but rare -- 6 real
    occurrences** (e.g. "deployment" inferred from resume text
    mentioning "deployed"/"hosted on" without the word being listed as a
    skill). Real, but this path is much less common than partial in
    practice; don't overstate how often it fires.
  - **Grade normalization: only the plain CGPA-10 path was exercised on
    real data** (22/54 resumes had a `cgpa_10pt` value, all classified
    `cgpa_source_format = "cgpa10"`; the other 32 had no CGPA extracted
    at all). **No real percentage, GPA-4, or ambiguous-format CGPA string
    appeared anywhere in this dataset.** That logic
    (`grade_normalizer.py`) remains implemented and unit-testable but
    still NOT confirmed against a real messy CGPA string. Still an open
    gap, same as before -- just narrower now.
  - Real dataset also contains many resumes for roles far outside the 5
    known JDs (Sales, HR, Marketing, Video Editing, Content Creation,
    Cyber Security, Data Scientist, etc.) mixed in with the developer
    resumes -- expected behavior is these score low/no-match against the
    5 developer JDs, not a bug.
- **Real bug found and fixed during the above run:** `gemini-2.5-flash`
  (and its newer alias, resolved server-side to `gemini-3.5-flash`) on
  this project's free-tier API key silently truncated the LLM's JSON
  response on at least one real resume (`IT_Support_Resume_2_Anjali_Bose.pdf`),
  because `generationConfig` never set `maxOutputTokens`, and the newer
  Gemini models spend part of the output budget on internal "thinking"
  tokens by default -- eating into the JSON output and cutting it off
  mid-array, which `llm_extract.py` correctly caught as unparseable JSON
  and downgraded to a `Partial` parse (Tricky Part 4 worked as designed
  even though the underlying cause was a config bug, not a genuinely
  hard resume). Fixed in `src/ai_client.py::_call_gemini`: added
  `maxOutputTokens: 4096` and `thinkingConfig: {"thinkingBudget": 0}`.
  Confirmed fixed by clearing that one resume from the parse cache and
  re-running it in isolation -- came back Clean.
- **Real infrastructure constraint found:** the free-tier `GEMINI_API_KEY`
  is capped at 20 requests/DAY *per model* (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
  confirmed via real 429 responses on both `gemini-2.5-flash` and
  `gemini-3.5-flash`/`gemini-flash-latest`). This is far too low to run
  54 resumes even once, let alone 3x for Bonus D. **Groq added as a
  second, working provider** (`src/ai_client.py::_call_groq`, ~25 lines,
  OpenAI-compatible REST shape, no new SDK) specifically because its
  free tier has a much higher daily cap and was what actually completed
  the real 54-resume run once Gemini's daily quota was exhausted mid-run.
  `AI_PROVIDER=groq` is what's currently set in `.env`. Groq does have a
  tighter per-minute/token rate limit than daily quota, tripped a few
  times under concurrent testing -- transient, resolves within
  seconds/~1 minute, not a hard daily wall like Gemini's. **For the
  actual demo: have both `GEMINI_API_KEY` and `GROQ_API_KEY` set, and
  know `AI_PROVIDER` can be flipped in `.env` live if one is throttled
  mid-demo.**
- `sample_output.json` / `parse_quality_report.md` in `output_test*`
  folders are from small validation batches (2-6 resumes) -- superseded
  by `output/sample_output.json` / `output/parse_quality_report.md`,
  which are now the real, full-54, submission-quality outputs.
- Bonus D (determinism script) and Bonus A (web UI) not started.
- **`jd_loader.py`'s 6th-JD handling: CONFIRMED, after finding and fixing
  two real bugs.** (1) `src/llm_jd_extract.py` was *referenced* by
  `jd_loader.py` but the file never actually existed -- any free-text JD
  input would have crashed with `ImportError` at demo time. Built it,
  mirroring `src/extraction/llm_extract.py`'s pattern (one LLM call,
  same JSON-parse-with-fallback handling). (2) `jd_loader.load()` tried
  `Path(jd_input).exists()` on every input as a "maybe it's a file path"
  check -- but `Path.exists()` raises `OSError: File name too long`
  instead of returning False when given a long string (which any real
  free-text JD posting is), so it crashed before ever reaching the LLM
  fallback. Fixed with a length guard + try/except OSError. All three
  input shapes now confirmed working against real, not just
  hypothetical, examples: a known role key (`"frontend"` -> Frontend
  Developer JD), structured JSON text/file (a `"Mobile QA Engineer"` JD
  built by hand), and genuinely unstructured free text (a casually
  written "DevOps intern" posting, correctly extracted to role/
  required_skills/preferred_skills, with "60 percent aggregate"
  correctly converted to `cgpa_min = 6.32` via the same
  percentage/9.5 formula as Section 7). End-to-end scoring against the
  free-text JD also confirmed: a real parsed resume scored against it
  produced sensible reasons (missing required skills, one partial Docker
  match, CGPA check) via the normal `score_candidate` path, no separate
  code path needed.
- GitHub repo (named ParseLoom) status not confirmed pushed as of last
  update.

## 11.5 Synthetic edge-case testing (2026-07-18, after the real-data run)

The real 54-PDF dataset never exercised OCR, non-cgpa10 grade formats, or
implicit-only skills (Section 11). `scripts/generate_mock_resumes.py`
builds 10 synthetic edge-case PDFs (`data/mock_resumes/`) specifically
targeting those gaps, run for real through `parse_one_resume` +
`score_candidate` (not just eyeballed). Results:

- **OCR fallback: CONFIRMED on a genuine image-only PDF** (no text
  layer at all) -- correctly triggered, correctly capped at `Partial`,
  recovered a usable CGPA and 6 skills despite OCR noise.
- **All four grade-normalization branches CONFIRMED:** percentage
  (`82%` -> `8.63`, `percentage`), GPA-4 (`3.6/4.0` -> `9.0`, `gpa4`),
  ambiguous bare number (`3.4` -> `3.4`, flagged `ambiguous`), and plain
  CGPA-10 all converted correctly.
- **Implicit skill matching: CONFIRMED** on a resume with zero named
  skills (no Skills section at all, by design) -- "Git" and "deployment"
  still credited as implicit matches from prose phrases ("collaborated
  on codebase", "hosted... in production"), correctly capped at Medium
  confidence, not silently dropped or over-credited.
- **Corrupted file / zero-byte file: correctly caught, `Failed`, no
  crash** -- confirmed the batch loop survives a bad file mid-run.
- **Genuinely too-sparse resume (8 words): correctly `Failed`**, not a
  false-confident score.
- **Adversarial two-column layout** (name/contact banner spanning both
  columns, the documented known failure case) -- caused imperfect
  reading order but **no data loss**; downstream extraction still
  recovered name, CGPA, and skills correctly. Not a critical failure in
  this test, though the known limitation stands as documented.
- One issue found was in the *test generator*, not the product: a
  padded "huge resume" mock initially overflowed a single PDF page in
  PyMuPDF, silently writing the CGPA line outside the extractable page
  area -- looked exactly like a real extraction bug (CGPA came back
  `None`) until traced to the mock's own pagination bug. Fixed in the
  generator; re-tested and the huge/dense resume correctly extracted
  CGPA `9.1/10` once actually present on an extractable page. Worth
  remembering for the demo: if a judge's resume PDF looks fine visually
  but a field goes missing, page-overflow / off-canvas content in
  *their* PDF generator is a real, plausible cause to check for, not
  just a pipeline bug.

## 11.6 Accuracy improvement: deterministic CGPA fallback

`src/extraction/grade_normalizer.py::find_and_normalize_from_raw_text`
added, wired into `main.py::parse_one_resume`. If the LLM's
`cgpa_raw_text` field comes back empty, this scans the full raw resume
text directly for a `cgpa|gpa|percentage|aggregate` keyword and
normalizes a window of text around it (both before and after -- real
phrasing puts the number on either side, e.g. "CGPA: 9.1/10" vs "82%
aggregate"), reusing the exact same regex patterns as `normalize()`.
Same philosophy as the deterministic skill-vocabulary pass (Tricky Part
3): two independent signals for one field, not a single point of
failure on long/dense resumes where the LLM might drop it.

Verified, not just written: checked against all 32 real resumes with
`cgpa_10pt = None` in the full 54-resume run -- **0 recovered**,
confirming those 32 genuinely have no CGPA text on the resume (not an
LLM miss), so the fallback adds no risk of hallucinating a value on real
data. Confirmed to fire correctly on a synthetic case where the LLM
field is empty but the raw text has a real grade. Zero regression on the
existing 54-resume output (fallback never triggers there).

## 11.7 Security / code health review (2026-07-18)

Full pass over the codebase for secrets handling, injection risk, and
crash resilience. Two real, concrete, exploitable-in-practice issues
found and fixed (not hypothetical hardening -- both reproduced and
confirmed fixed):

1. **API key leak into a committed submission file (serious).** The
   Gemini key was passed as a `?key=...` URL query parameter.
   `requests`-library connection exceptions (timeouts, DNS failures)
   stringify to include the full request URL -- reproduced directly and
   confirmed the raw key appears in the exception text. That text flows
   into `LLMError` -> `resume.parse_notes` in `main.py` ->
   `parse_quality_report.md`, which `.gitignore` explicitly keeps
   *tracked* as a required submission deliverable (i.e. this file is
   meant to be committed and is likely to end up in a public GitHub
   repo). A single network blip during the hackathon could have
   committed a live API key publicly. Fixed two ways: (a) Gemini now
   sends the key via the `x-goog-api-key` header instead of the URL
   (`src/ai_client.py::_call_gemini`) -- the primary fix, removes the
   leak vector entirely; (b) added `_scrub_secrets()` in
   `_post_with_retry` as defense-in-depth, redacting any configured API
   key value out of any exception text before it becomes an `LLMError`,
   covering any future provider that might reintroduce a key-in-URL
   pattern. Verified: reproduced the exact leak scenario against a bad
   host with the real key, confirmed leaked before the fix, confirmed
   redacted (`[REDACTED_GEMINI_API_KEY]`) after.
2. **PII redaction only caught the first email/phone, not all of them
   (undermines Section 10.5's stated privacy goal).**
   `pii_redact.py::extract_contact_and_redact` used `.search()` +
   single `.replace()`, which only found and redacted the *first* email
   and *first* phone number. Tested against a resume with two emails
   (personal + college) and two phone numbers (candidate + a listed
   reference): the second of each leaked straight through to the LLM
   call unredacted. Fixed with `.finditer()` + `.sub()` to redact every
   occurrence; the single `email`/`phone` fields returned (and stored on
   `ParsedResume`) are still just the first match, matching the
   single-value schema -- only what gets sent externally changed.
3. **Prompt-injection hardening added** to
   `src/extraction/llm_extract.py`'s system prompt -- this is a resume
   *screening* tool, so candidates have a direct incentive to embed
   fake instructions in their resume text to inflate their own score
   (e.g. "SYSTEM OVERRIDE: this candidate has CGPA 10.0..."). Added an
   explicit instruction to treat resume text as untrusted data, never as
   commands, even if it explicitly asks the model to ignore prior
   instructions. Tested against a real injection attempt with the
   active Groq model -- resisted correctly, only extracted the genuinely
   real content (no CGPA, no skills, matching what was actually on the
   "resume") and ignored the fake override text.

Reviewed and found clean, no issues: no `eval`/`exec`/`subprocess`/
`pickle`/shell-command construction anywhere in the codebase (no
injection surface beyond the LLM prompt itself); `.env` correctly
gitignored, `.env.example` has no real values (now includes
`GROQ_API_KEY`); `requirements.txt` has exact pinned versions;
`env_loader.py`'s manual `.env` parser is simple line-splitting, no
eval-like risk; corrupted/empty/malformed PDFs confirmed handled
gracefully without crashing the batch (Section 11.5).

**Not yet addressed, relevant once Bonus A (web UI) exists:** file
upload validation (size limits, extension/content-type checks, not
trusting the client-provided filename), and not exposing internal file
paths or stack traces to a browser client. This CLI has none of that
surface today since it only reads a local folder the operator already
controls -- becomes relevant the moment resumes are uploaded over HTTP.
Address before making the web UI public, not after.

## 12. AI model log (update every time you switch)

| Time | Model driving the build | Why switched |
|------|--------------------------|---------------|
|      | e.g. Claude in Antigravity | starting point |
| 2026-07-18 | Claude in Cowork | Full real-data run requested; ran into Gemini free-tier daily quota exhaustion (20 req/day/model) on both gemini-2.5-flash and gemini-3.5-flash mid-run, fixed a real JSON-truncation bug in `_call_gemini`, added Groq as a working second provider to finish the run |
