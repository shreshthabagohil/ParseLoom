# TASKS.md — mapped to the actual event clock

Check items off as you go. Whichever AI tool you switch to next reads
this file first — it should be able to tell exactly what's done without
you re-explaining anything.

## 9:00 – 9:30 AM — Registration / environment check
- [ ] `python3 --version` (3.11+)
- [ ] `pip install -r requirements.txt` succeeds clean
- [ ] `tesseract --version` works (system binary, not pip — this is the
      one real setup risk in this stack, verify it now, not at 11am)
- [ ] At least one AI provider key set and a test call succeeds
- [ ] Drive folder downloaded locally the moment it's live — do not
      depend on live Drive access during the build

## 10:00 – 11:00 AM — Stage 1: parsing only, nothing else
- [ ] `pdf_reader.py` extracts text from a real single-column resume
- [ ] Column-split logic works on a real two-column resume
- [ ] OCR fallback triggers correctly on the scanned resume, produces
      usable text
- [ ] Every resume in the folder gets a `parse_status` — Clean, Partial,
      or Failed — none silently skipped
- [ ] Do not touch scoring logic yet, even if tempted

## 11:00 – 11:30 AM — Structured extraction + grade normalization
- [ ] `llm_extract.py` returns structured JSON for a parsed resume
- [ ] Grade normalization handles CGPA-10, percentage, and GPA-4 cases,
      plus the ambiguous bare-number case
- [ ] Skill vocabulary + synonym map covers all required/preferred
      skills across the 5 known JDs

## 11:30 AM – 12:15 PM — Scoring engine
- [x] Skill matching classifies exact/synonym/partial/implicit
- [x] CGPA eligibility gate routes below-minimum candidates to Reserve,
      never drops them
- [x] Partial parse caps confidence at Medium — verified in a real run
- [x] Failed parse produces zero score, only a flag

## 12:15 – 12:30 PM — Shortlist assembly + JD loader + CLI
- [x] Slot-aware shortlist + Reserve list working
- [x] JD loader accepts a structured 6th JD (jd_loader.py) — demo-tested
      with a real unstructured "DevOps intern" posting; found and fixed
      two real bugs (missing llm_jd_extract.py module, and a
      Path.exists() crash on long free-text input) — see
      PROJECT_CONTEXT.md Section 11
- [x] CLI runs end to end: `python main.py --resumes data/real_resumes --jd frontend`
      — verified against real resumes with a real Gemini key. Fixed a
      real bug found in this test: Gemini 503 (model overloaded) wasn't
      being retried, only 429 was. Now retries with exponential backoff
      on 429/500/502/503/504.

## 12:30 – 1:00 PM — Lunch (commits during this window get flagged — don't push)

## 1:00 – 1:45 PM — Full run on real data, fix what breaks
- [x] Run against the entire real Drive folder for all 5 JDs -- 54/54,
      confirmed by reading the real output files (see
      PROJECT_CONTEXT.md Section 11)
- [x] Generate `output/sample_output.json` and
      `output/parse_quality_report.md` -- done, real 54-resume data
- [x] Fix whatever real, messy resumes break that synthetic test data
      didn't catch -- found + fixed a Gemini JSON-truncation bug
      (missing maxOutputTokens/thinkingConfig), found + worked around a
      Gemini free-tier daily quota wall by adding Groq as a second
      provider (see PROJECT_CONTEXT.md Section 11)

## 1:45 – 2:15 PM — Bonuses, only if core is solid
- [ ] Bonus C (live JD parsing) — already covered by the JD loader
      design, just confirm it demos cleanly
- [x] Bonus D (score stability) — `scripts/score_stability_test.py`
      built, real result: 3 real resumes x 3 JDs-worth of pairs x 3
      fresh LLM-parse runs (Groq) = 15 (candidate, JD) pairs, **0.0 point
      drift on every single pair** (see
      `output/score_stability_report.md`). NOTE ON SCOPE: sandbox has a
      hard ~45s-per-command limit which made a larger sample (tried 6
      and 10 resumes) time out mid-run before writing output — the
      script itself supports `--limit`/`--runs` for any size and isn't
      the bottleneck, the exec environment is. Re-run with a higher
      `--limit` (or omit it for all 54) on your actual machine, which
      won't have this constraint, for a fuller sample before the demo if
      you want more than 3 data points.
- [ ] Bonus B (OCR fallback) — already core, just rehearse demoing it
      live on the scanned resume. NOTE: no scanned resume exists in the
      real dataset (see Section 11), so this cannot be rehearsed on real
      data — only on the synthetic scanned test file from last night.
- [ ] Bonus A (web UI) — only attempt if everything above is done

## 2:15 – 2:45 PM — Required docs
- [ ] `DESIGN_DECISIONS.md` — the four Tricky Parts, one paragraph each,
      actual implementation not theory (draft already exists, just
      confirm it still matches what got built)
- [ ] `AI_USAGE_LOG.md` — max 200 words
- [ ] `README.md` — setup + a working example run in under 5 minutes

## 2:45 – 3:00 PM — Final commit, buffer
- [ ] Fresh clone + `pip install` + run, confirm it actually works clean
- [ ] Final commit pushed

## 3:00 – 3:30 PM — Submit
- [ ] Parse quality report, Design Decisions doc, AI Usage Log submitted

## Before 3:30 PM demo — rehearse these two answers out loud
- [ ] "Which resume gave your parser the most trouble, and why?"
- [ ] "What would your engine get wrong on a resume it's never seen?"
      (Both have no single right answer — they're graded on whether your
      answer shows you understand your own system's limits.)

## Commit discipline
Commit after every working milestone above, not at the end. `git log
--oneline` should tell a fresh AI tool exactly where things stand.
