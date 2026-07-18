# SESSION HANDOFF — paste this whole file into a new session first message

Written 2026-07-18, ~17:30 IST. Hackathon submission form is already
submitted. A second demo/judging round is still ahead. If you're a fresh
AI session reading this: read `PROJECT_CONTEXT.md` next for full
architecture/history, this file is just "what's true right now and what
to do next."

## 1. What this project is

InternLoom Resume Shortlisting Engine (AI Dev track), repo name
ParseLoom. CLI engine (`main.py`) that takes a folder of PDF resumes + a
job description, produces a ranked/scored/explainable shortlist with
honest parse-quality flags. Plus a Flask web UI (`app.py`, Bonus A) built
on top of the exact same `src/` logic. Full architecture, the "Four
Tricky Parts," and scoring formula are documented in
`PROJECT_CONTEXT.md` and `DEMO_PITCH_GUIDE.md` — read those before
re-deriving anything.

## 2. Correctness status (the thing being second-guessed right now)

The scoring/parsing logic itself has been hand-verified multiple times
today against real output, most recently by manually recomputing an 8.8
score from a real web-app run and getting an exact match to the formula
in `src/matching/scorer.py`. **The logic is correct and has been proven
correct repeatedly, not just asserted.** If it's questioned again, the
fastest way to re-verify: pick any candidate card, read its required/
preferred skill matches and completeness signals (name/CGPA/projects
present or not), and hand-compute
`skill_subscore = required_avg*70 + preferred_avg*30`, then
`final_score = skill_subscore * (0.5 + 0.5*completeness)`, completeness
= fraction of {name, CGPA, skills-list-populated, projects-or-experience}
present. It will match the displayed score.

What genuinely varies run-to-run and is NOT a bug: LLM extraction
quality on messy/OCR'd resumes. A resume can score low or show "Name not
extracted" honestly because the resume itself barely parsed (Partial
status) — that's the intended behavior (confidence/score should be
low for bad input), not the engine being wrong. If a candidate's card
shows "Parse: Partial" and thin data, a low score is *correct*, not a
symptom of a bug.

"AI Match" (the score label in the web UI) is Fable's frontend naming,
not mine. Be precise if asked: extraction is AI-assisted, the
match/scoring math itself is deterministic and auditable (not an LLM
opinion). Worth saying proactively if a judge asks "what does AI match
mean" — it's a strength (auditable), frame it that way.

## 3. Critical action item — NOTHING FROM TODAY IS PUSHED TO GITHUB YET

`git status` right now shows uncommitted changes to `app.py`,
`static/style.css`, `templates/index.html`, a new untracked
`templates/candidate.html`, and a staged `requirements.txt`. This
includes ALL of today's fixes (see Section 4). Last real commit on
GitHub is `dfbefd8` ("Add Bonus A web UI..."). There's also a later
commit `7ea6d34` ("Prepare for Render deployment") that was made
directly by the user in their own terminal, not by this AI session --
worth knowing it exists but its contents haven't been reviewed here.

**Before anything else, from the user's own terminal (not from an AI
sandbox -- a prior session hit unfixable `.git/index.lock` permission
issues trying to commit from its sandboxed environment):**

```
cd "/Users/shreshtha/Cllg hackathon/ParseLoom"
git add -A
git status   # sanity check the file list before committing
git commit -m "Fix candidate detail overflow, add dedicated detail page, parallelize resume parsing, fix drag-and-drop and dead nav links"
git push origin main
```

## 4. What changed today, not yet pushed (in build order)

1. **Purple → warm palette rebrand** (`static/style.css`): teal/gold
   first, then further shifted to a charcoal/slate/warm-tan/cream
   palette per the user's uploaded swatches. Verified zero purple
   remains via grep.
2. **Fixed native file-input chrome** ("No file chosen" text bleeding
   through next to the custom "+ Select Files" button) --
   `templates/index.html` / `static/style.css`.
3. **Real drag-and-drop wired up** on the "Drop Resumes Here" box --
   previously the label was true in text only, dragging files onto it
   did nothing.
4. **Removed dead nav links** (Analysis/History header links, footer
   links) that went to `href="#"` and did nothing -- header now just has
   "Dashboard", footer links are plain non-clickable labels.
5. **Fixed a real display bug**: candidate cards fell back to showing
   the PDF filename twice (once as name, once as meta) when no name was
   extracted. Now shows "Name not extracted" honestly instead of a fake
   duplicate.
6. **Full per-candidate detail view added** (`app.py`'s `/api/run` now
   also returns a `details` dict: college, degree, grad year, CGPA +
   source format, full skill list, projects, experience, certifications,
   and the COMPLETE required/preferred skill match breakdown, not just
   the top-3 reasons already in the CLI's canonical output). This is
   additive, web-only, doesn't touch `shortlist.py`'s CLI-facing schema.
7. **Moved that detail view to its own page** (`templates/candidate.html`,
   new file + new `/candidate` route in `app.py`). It was originally an
   inline expand-in-card panel, which caused a real horizontal-overflow
   bug on real data (text got cut off mid-word because a 2-column skill
   breakdown was nested inside an already-narrow card). The dedicated
   page opens in a new tab (`target="_blank"`, no `rel="noopener"` so it
   inherits a clone of `sessionStorage`), gets the full viewport to lay
   out in, and can't regress into that overflow bug again. No server
   state/session needed -- it just reads the same `/api/run` JSON back
   out of `sessionStorage`.
8. **Parallelized resume parsing** in `/api/run`
   (`concurrent.futures.ThreadPoolExecutor`, `max_workers=4`) --
   previously resumes were parsed one at a time in a for-loop, each
   waiting on a real LLM network call. This was the actual cause of the
   "takes too long" complaint. Bounded at 4 workers deliberately, not
   unbounded, to avoid bursting past Groq/Gemini's per-minute rate limit
   (a real transient failure mode already hit once today). Order is
   preserved (`executor.map`). Verified with a synthetic delay test (no
   LLM quota spent) that it's genuinely concurrent and order-preserving.
9. **Flask auto-reload turned on**
   (`app.run(debug=False, use_reloader=True, port=5000)`). Root-caused a
   real bug today: templates hot-reload on browser refresh, but
   `app.py`'s route code does not -- a running server was silently
   serving old backend logic after a code change, with no visible error.
   `use_reloader` is independent of `debug` (the interactive-debugger
   security risk stays off); this just restarts the process automatically
   on `app.py`/`src/` changes.
10. **`.results-grid` changed to single-column, full width** (was a
    responsive `auto-fill, minmax(320px, 1fr)` multi-column grid) --
    more robust against viewport-size-dependent cramping.

All of the above were verified via: `pytest tests/` (29 tests, still
passing), Node.js `--check` on extracted `<script>` blocks (JS syntax
valid), a CSS brace-balance count, and Flask's test client hitting real
routes (`GET /`, `GET /candidate`, `GET /candidate?file=...`) for a 200.
The concurrency change was verified with a synthetic sleep-based test,
not real LLM calls, to avoid spending quota. **None of this was visually
confirmed in a real browser by the AI itself** (no computer-use/browser
access this session) -- confirmation came from the user's own
screenshots after each change. If picking this up fresh, a real click
-through in the browser is worth doing once, even though the code-level
checks all pass.

## 5. Known-fragile things to watch (not broken, just worth knowing)

- **LLM provider quota**: Gemini free tier hit its daily cap multiple
  times today. `.env` currently has `AI_PROVIDER=groq` and both keys
  populated; Groq was confirmed working with a real test call today
  (`load_env()` then `call_llm(...)` returned "OK"). Groq also has a
  transient per-minute rate limit -- if a batch run comes back
  suspiciously all-Partial with no names, that's the most likely cause;
  wait ~30-60s and retry, don't assume something is broken.
- **`app.py` route code changes require the reloader to pick them up**
  (now automatic per item 9 above, but if `use_reloader` is ever removed
  or the server started with something other than `python3 app.py`,
  this class of bug can resurface).
- **`.venv` must be activated** each new terminal session:
  `source .venv/bin/activate` before `python3 app.py`.
- The user is on a **school-managed Chrome profile** that blocks
  `127.0.0.1`/`localhost` outright (real HTTP 403 from a content
  filter, not a code bug) -- Safari works fine for the same URL. This
  bit them once already; don't re-diagnose it as a server bug if it
  comes up again.
- The repo's remote is `https://github.com/shreshthabagohil/ParseLoom.git`,
  currently set to **Private** (confirmed by the user earlier) -- unclear
  if it's been switched to Public since; worth asking/checking before
  final judging if visibility matters for the submission.

## 6. Things NOT done / explicitly deferred

- The reactbits.dev "Strands"-style animated component the user asked
  about earlier was explicitly **not** integrated -- it's a React/WebGL
  component, this is a vanilla Flask/HTML/CSS/JS app, and pulling in a
  React-only animation library this close to a deadline was judged too
  risky. If revisited, a CSS-only ambient animation (gradient drift,
  no new dependency) is the safer equivalent already discussed.
- `templates/results.html` is a leftover placeholder, not actually used
  in the live flow (results render inline via JS into `index.html`'s
  `#results-container`, and now also via the new `/candidate` page).
  Fine to ignore or delete later.
- No automated visual/browser test suite exists for the web UI --
  `pytest tests/` only covers `scorer.py` / `grade_normalizer.py` /
  `skill_matcher.py` pure logic, not the Flask routes or frontend JS.

## 7. Immediate next steps, in order

1. Run the git commands in Section 3 from the user's own terminal.
2. Do one real click-through in the browser (Safari) of: upload 3-4
   resumes → run → click "View full details" on a couple of candidates
   (including one with a low/Partial score) → confirm the new
   `/candidate` page renders cleanly with no cut-off text.
3. Re-read `DEMO_PITCH_GUIDE.md` before the next judging round --
   it has the full rehearsed Q&A, the scoring formula worked example,
   and the "own your limitations" list.
4. Confirm GitHub repo visibility (Public vs Private) is what the user
   wants for final submission.
