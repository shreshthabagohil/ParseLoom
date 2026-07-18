# Demo & Pitch Guide — ParseLoom / InternLoom Resume Shortlisting Engine

Everything to know cold before judging. Written from what was actually
built and verified today, not the original plan — if a judge asks
something not covered here, the honest answer is "I don't know, here's
how I'd find out," not a guess. That answer is *correct* for this
project, not a weakness — see Section 8.

---

## 1. The 30-second pitch

"We built a CLI engine that takes a folder of real, messy PDF resumes
and a job description, and produces a ranked, scored, explainable
shortlist — with an honest parse-quality flag on every single resume,
so nothing gets a confident-looking score it hasn't earned. The core
insight: on real, messy data, the right target isn't chasing a fake
'99% accurate' number — it's sorting the easy majority reliably and
being explicit about the rest, so a human reviewer knows exactly where
to look."

## 2. The problem, restated simply

Given: a folder of real resumes (PDF, inconsistent formatting,
multi-column layouts, some scanned) and a job description (one of 5
known roles, or an arbitrary 6th). Produce: a ranked shortlist with
scores, confidence levels, and 3-bullet explanations per candidate —
plus a parse-quality report covering every resume, whether it scored or
not. Two stages: extraction (PDF → structured data, the harder,
heavier-weighted stage) then matching (structured data → score against
the JD).

## 3. Why we chose this track

Three tracks were offered: Web Dev, AI Dev, App Dev. Reasoning, if
asked: the hardest sub-problems in AI Dev (multi-column layout, skill
extraction from unstructured text) have LLM-delegated solutions the
problem statement itself sanctions — that plays to prompt-engineering
strength rather than deep systems fundamentals. Web Dev required
self-implemented auth from scratch, which conflicted with prior prep
and is hard for reasons AI-generated code can't fully cover. App Dev
needed Flutter with zero prior familiarity and an emulator dependency —
highest environment risk of the three.

## 4. Architecture, one paragraph

Python 3.11+, stdlib-first. PyMuPDF (`fitz`) for both text+bounding-box
extraction and page rasterization (one library instead of two, less to
explain). `pytesseract` + Pillow for OCR fallback. Plain `requests`
against provider REST APIs (no heavy SDK) — `call_llm()` is
provider-agnostic, switching between Gemini/OpenAI/Anthropic/Groq is an
env var change, not a code change. Data models are plain
`dataclasses`, no pydantic — no validation magic to explain under
pressure. CLI is stdlib `argparse`. Output is JSON + Markdown.

## 5. The two stages

**Stage 1 — Extraction (`src/extraction/`).** PDF → `ParsedResume`. Text
extraction with column-awareness, OCR fallback when text yield is low,
PII redaction (email/phone pulled out locally *before* anything reaches
an LLM), one LLM call for structured fields (name, college, skills,
projects, experience, CGPA), then deterministic grade normalization.

**Stage 2 — Matching (`src/matching/`).** `ParsedResume` + `JobDescription`
→ `ScoreResult`. Hybrid skill classification (exact/synonym/partial/
implicit/none), weighted scoring, a bounded signal-conflict adjustment,
and confidence derivation that's hard-gated by parse quality.

## 6. The Four Tricky Parts — what to actually say

**1. Multi-column layout.** `page.get_text("blocks")` gives bounding
boxes; blocks are split left/right by x-midpoint and read left column
first, only when both sides have ≥2 blocks (avoids a single stray block
triggering a false split). **Real result: 31 of 54 real resumes
genuinely triggered this, output stayed coherent.** Known failure case,
say it unprompted: a full-width name/header banner spanning both
columns can get pulled into one side — tested this deliberately with a
synthetic adversarial resume, it caused imperfect ordering but **no
data loss**. True 3-column layouts approximate as two, untested.

**2. Scanned resumes.** Word count < 50 after standard extraction →
rasterize at 300 DPI → pytesseract. If OCR also yields < 50 words →
`Failed`, explicit note, no guessed score. **Real result: confirmed
working on a genuine image-only synthetic PDF** (OCR fired, recovered a
real CGPA and 6 skills, correctly capped at Partial). Honest caveat:
**no resume in the real 54-file dataset happened to be scanned**, so
this path is confirmed on synthetic data, not a real example from the
event. Say this proactively if asked "did OCR fire on real data" — the
honest "no, and here's why that's not a red flag" is a stronger answer
than dodging.

**3. Skill extraction from unstructured text.** Hybrid: a curated
vocabulary+synonym pass across the *full* text (not just a "Skills"
section, catches inline mentions), plus one LLM call for full
structured extraction. **Real result: 114 real partial matches, 6 real
implicit matches** (e.g. "deployment" inferred from "hosted... in
production" phrasing without the word "deployment" ever appearing) —
implicit matching is genuinely rare in practice, don't oversell it.
Misses: brand-new/obscure tool names neither list recognizes.

**4. Parse quality gates confidence — this is the one to lead with.**
Clean → can reach High. Partial → hard-capped at Medium, no matter how
good the visible data looks. Failed → **no score at all**, only a flag
and a human-review recommendation. Lives in one function
(`scorer.py::score_candidate`) so it can't be silently bypassed. This
is the actual answer to "how do you ensure accuracy" — see Section 8.

## 7. Scoring formula — worked example

```
skill_subscore = required_score * 70 + preferred_score * 30   (0-100)
adjusted = skill_subscore + signal_conflict_delta (±5, bounded)
final_score = adjusted * (0.5 + 0.5 * completeness_fraction)
```

`completeness_fraction` = share of {name, cgpa, skills, ≥1 project/exp}
present. A 40%-complete resume is meaningfully penalized, never zeroed
(the 0.5 floor guarantees that). CGPA below the JD minimum never
excludes a candidate — flagged `below_cgpa_minimum` and routed to
Reserve, always visible, never silently dropped.

If asked to walk through a real number: a candidate matching all
required skills exactly (`required_score=1.0`), 2 of 3 preferred
(`preferred_score=0.67`), no conflict adjustment, 100% complete:
`skill_subscore = 70 + 20 = 90`, `final_score = 90 * 1.0 = 90.0`.

## 8. The philosophy to lead every hard question with

**"The engine's job is to reliably sort the easy majority and honestly
flag the rest for a human — never to produce a confident-looking number
it can't back up."** This was a specific judge note from an earlier
round of feedback, documented as a named design principle
(PROJECT_CONTEXT.md Section 10.5), not something bolted on for the
pitch. Three concrete places this shows up: a Failed parse gets zero
score, a Partial parse is hard-capped at Medium confidence regardless
of how good the data looks, and an ambiguous CGPA scale assumption is
stated outright in the output rather than silently guessed. If a judge
asks "how do you know it's 99% accurate" — the honest, *stronger*
answer is that chasing a single accuracy number on real messy data is
the wrong target; the actual deliverable is confidence and
parse-quality flags that are honest, not a number that's confidently
wrong some of the time.

## 9. Real numbers to have ready

- 54/54 real resumes: **Clean, 0 Partial, 0 Failed** on the actual
  event dataset (Gemini/Groq LLM extraction succeeded on every one).
- 31/54 real resumes triggered genuine two-column splitting.
- 114 real partial skill-match instances, 6 real implicit-match
  instances, across 54 resumes × 5 JDs.
- 22/54 real resumes had a CGPA (all plain CGPA-10 format); the other
  32 genuinely had none on the resume (confirmed by a deterministic
  fallback scan finding nothing, not an LLM miss).
- Score stability (Bonus D): **0.0 point drift** across 3 real resumes
  × 5 JDs × 3 fresh LLM-parse runs (15 pairs, all identical). Honest
  caveat: sandbox time limits kept this to a 3-resume sample, not the
  full 54 — script supports any size, worth a bigger run if asked to
  demonstrate live.
- 29 automated tests (`pytest tests/`), 0.04s runtime, covering the
  scoring/matching/grade-normalization logic — most hackathon
  submissions won't have this, it's worth mentioning unprompted.
- 3 real security issues found and fixed during testing (Section 14) —
  also worth mentioning unprompted, it shows the codebase was actually
  stress-tested, not just built and hoped for.

## 10. Live demo script

Recommended order, ~3-4 minutes:

1. **Show the folder structure and `PROJECT_CONTEXT.md` for 10
   seconds** — "this is our single source of truth, every design
   decision is documented and dated."
2. **Run the core command:**
   ```
   python main.py --resumes data/mock_resumes --jd frontend
   ```
   (Use `data/mock_resumes/` if live-demoing without a fresh real
   folder handy — it's checked into the repo, deterministic, and
   deliberately hits OCR/every CGPA format/a corrupted file/etc. If
   demoing against real data, use `data/real_resumes` the same way.)
3. **While it runs, narrate the two stages** (Section 5) — this fills
   the ~1-20s per-resume LLM call time usefully instead of dead air.
4. **Open `output/parse_quality_report.md`** — point at the
   Clean/Partial/Failed column, say explicitly: "every resume gets a
   status, none silently skipped."
5. **Open `output/sample_output.json`** — walk through one Shortlist
   entry: score, confidence, the 3 reasoning bullets. Read one bullet
   aloud verbatim — it's plain English, not a debug dump.
6. **Bonus C, live:** run `--jd` with a pasted free-text JD (have one
   ready, e.g. the "DevOps intern" example from testing) to show the 6th
   -JD path working on something the system has never seen.
7. **If time allows:** `pytest tests/` — 29 passed in <1s, "this is what
   stops us from silently breaking something we already verified."

## 11. If the live demo breaks (have this ready, don't panic)

Most likely failure: an LLM provider rate limit (real, hit this twice
during testing today — Gemini's free tier is 20 requests/day *per
model*, Groq has a tighter but transient per-minute limit). If it
happens live:
- Say what's happening plainly: "this is a free-tier rate limit, not a
  bug — here's the real error message, and here's why the retry logic
  handles it" (point at `_post_with_retry`'s exponential backoff).
- Flip `AI_PROVIDER` in `.env` to the other configured provider
  (Gemini ↔ Groq) and re-run — have both keys valid before you go up.
- Fall back to already-generated `output/sample_output.json` /
  `output/parse_quality_report.md` from the real run and walk through
  those instead of re-running live.

## 12. Questions to rehearse out loud (the two required ones, plus more likely ones)

**"Which resume gave your parser the most trouble, and why?"** Be
specific, not vague: a huge, artificially padded synthetic resume
initially came back with a missing CGPA — traced it to a *test-data*
bug (content overflowing a single PDF page in the generator, not a
parsing bug), fixed the generator, re-confirmed extraction worked once
the content was actually on the page. On real data, the closest thing:
one real resume's LLM response got silently truncated mid-JSON because
newer Gemini models spend part of their output budget on hidden
"thinking" tokens and `maxOutputTokens` wasn't set — found via a real
`Partial` parse, fixed by explicitly setting `maxOutputTokens` and
disabling the thinking budget.

**"What would your engine get wrong on a resume it's never seen?"**
Three honest answers, pick based on what's being probed: (1) a resume
using very new or unusual tool/technology names not in the curated
vocabulary and phrased in a way the LLM also doesn't recognize as a
skill; (2) a true 3-column layout, which only approximates as two;
(3) a resume whose only academic-performance number is a bare 0-4 value
with no label — genuinely ambiguous between a low CGPA and a GPA-4
scale, and the engine says so explicitly (`ambiguous`, capped
confidence) rather than guessing.

**"How do you know your scoring weights (70/30, ±5, the completeness
formula) are correct?"** They're not empirically validated against
human-judged "good" rankings — no one manually re-ranked the real
shortlist against what a recruiter would produce by hand. They're
documented, bounded, explainable design decisions (DESIGN_DECISIONS.md),
not a black box. That's the honest answer, and it's a fine one: the
alternative (an opaque model-derived weight) would be *harder* to
justify, not easier.

**"Is this secure? What about candidates gaming it?"** Yes, actively
tested for this — three real issues found and fixed (Section 14),
including prompt-injection hardening tested against an actual fake
"SYSTEM OVERRIDE" instruction embedded in resume text claiming a
perfect CGPA; the model correctly ignored it.

**"What's actually AI-generated vs. your own decision?"** See
`AI_USAGE_LOG.md` — the scoring weights, the confidence-capping rule,
and the human-in-the-loop philosophy were deliberate calls, not
AI-suggested. Most of the Python implementation and today's real-data
bug fixes were AI-assisted, verified by actually running the code and
reading real output, not by trusting that generated code "looked
right."

**"Why not just use one big LLM call for everything?"** Two reasons:
(1) auditability — the vocabulary pass gives skill matches a
non-LLM-dependent confidence signal, so a match can be explained without
re-asking the model; (2) data minimization — email/phone are extracted
locally via regex and redacted before anything reaches a third-party
API, which a single "send the whole resume" LLM call couldn't do.

## 13. Known limitations — own these before they're asked

- No real scanned resume in the dataset — OCR confirmed synthetically
  only.
- Score-stability testing was on a 3-resume sample, not the full 54,
  due to a sandbox time constraint during testing (not a pipeline
  limit — the script itself supports any size).
- No field-level accuracy ground truth exists for any submission in
  this event, as far as we know — "accuracy" is measured here as parse
  status + logic-path confirmation (partial/implicit/OCR/grade-format
  all genuinely fired on real or realistic data), not a precision/recall
  number, because no labeled answer key exists to compute one against.
- The web UI (Bonus A) is in progress, not finished as of this writing.
- Skill vocabulary and the implicit-match phrase list are hand-curated
  and finite — will always miss sufficiently novel phrasing, by design,
  not by oversight.

## 14. Security work done (mention unprompted — this is a real differentiator)

Three real, reproduced-and-fixed issues, not hypothetical hardening:
(1) the Gemini API key was in the request URL; a network-level failure
would have leaked it into a *committed* report file — fixed via
header-based auth plus a redaction safety net, reproduced the leak
before the fix and confirmed it's gone after. (2) PII redaction only
caught the *first* email/phone on a resume, not all of them — a second
contact detail leaked to the LLM undetected; fixed and verified against
a resume with two of each. (3) Prompt-injection hardening added and
tested against a real injection attempt. Separately: an early git
commit accidentally included a debug cache file with 54 real students'
names/emails/phones/full resume text — caught before submission, fixed
with a full git history rewrite (not just a delete-and-recommit, which
would have left it recoverable), verified via a fresh clone showing
zero matches for the leaked data afterward.

## 15. Tech stack rationale, if asked "why not X"

- Why not pdfplumber too: PyMuPDF alone does both text extraction and
  page rasterization for OCR — one library to explain under pressure,
  not two.
- Why not pydantic: plain dataclasses, no validation-magic to explain,
  `dataclasses.asdict()` covers the JSON output need.
- Why not a heavier LLM SDK: plain `requests`, one `call_llm()`
  function, provider switch is an env var not a code change — this is
  also *why* adding Groq as a fallback provider took ~25 lines, not a
  rewrite, when Gemini's free-tier quota ran out mid-testing.
- Why Flask (not FastAPI) for the web layer: closer to the rest of the
  codebase's "one function per concern, minimal magic" style; a
  student-level Python codebase shouldn't suddenly need async/Pydantic
  fluency to explain the web layer.

## 16. Standard identity questions

- **Team/project name:** ParseLoom (repo), "InternLoom Resume
  Shortlisting Engine" (problem-statement facing name).
- **What does it NOT do:** no auth, no database, no persistence across
  runs (by design, out of scope for this problem statement) — say this
  proactively if asked about "production readiness," it's a scoping
  decision, not a gap.
