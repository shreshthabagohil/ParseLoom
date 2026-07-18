# InternLoom Resume Shortlisting Engine

AI Dev Track — parses real, messy PDF resumes and scores them against
job descriptions, with explicit parse-quality and confidence flags on
every output so nothing is silently guessed.

Read `PROJECT_CONTEXT.md` before touching code — it has the full
architecture, the locked design decisions for the four Tricky Parts, and
the scoring formula. This README is just setup + run instructions.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Also required: the `tesseract-ocr` system binary (not pip-installable).

- macOS: `brew install tesseract`
- Ubuntu/Debian: `sudo apt install tesseract-ocr`
- Windows: install from https://github.com/UB-Mannheim/tesseract/wiki

Verify with `tesseract --version` before relying on the OCR fallback.

Copy `.env.example` to `.env` and add whichever AI provider key you have:

```
AI_PROVIDER=groq        # or openai / anthropic / gemini
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=
```

Note on providers, from a real run against the full dataset: the
`GEMINI_API_KEY` free tier is capped at **20 requests/day per model**,
which is not enough to parse more than a handful of resumes before
you'll hit a 429 (confirmed, see PROJECT_CONTEXT.md Section 11). Groq's
free tier (get a key at https://console.groq.com/keys) has a much higher
daily cap and is what actually completed a real 54-resume run — it's
the recommended default unless you have a paid-tier key for one of the
others.

## Run

`data/real_resumes/` is gitignored (real students' resumes are PII, see
`.gitignore`) — it won't exist on a fresh clone. To try the engine
immediately without real data, run it against the synthetic edge-case
resumes checked into `data/mock_resumes/` instead (covers OCR fallback,
all CGPA formats, implicit-only skills, a corrupted file, and more —
see PROJECT_CONTEXT.md Section 11.5):

```bash
python main.py --resumes data/mock_resumes --jd frontend
```

Once you have a real resumes folder locally:

```bash
python main.py --resumes data/real_resumes --jd frontend
python main.py --resumes data/real_resumes --all-jds
python main.py --resumes data/real_resumes --jd path/to/sixth_jd.json
```

Output is written to `output/sample_output.json` and
`output/parse_quality_report.md`. Verified end-to-end from a clean
virtualenv against `data/mock_resumes/` (10 resumes, ~8 seconds).

## Tests

```bash
pytest tests/
```

29 tests covering `scorer.py`, `grade_normalizer.py`, and
`skill_matcher.py` -- pure logic, no LLM calls, no API quota used, runs
in well under a second. Exists to catch regressions in the
parse-quality-gates-confidence rule (Tricky Part 4) and the grade/skill
matching logic, since those are the parts most likely to break silently
if edited later.

## Human-in-the-loop, by design

This engine never silently guesses on data it can't confidently read. A
resume that fails to parse (even after the OCR fallback) gets **no
score at all** — only a flag and an explicit recommendation for a human
to review it. A resume that only partially parses is capped at Medium
confidence regardless of how good its visible data looks. The engine's
job is to do the bulk sorting reliably and be honest about exactly where
it isn't sure — not to produce a confident-looking number for every
input regardless of whether the input actually supports one. See
`DESIGN_DECISIONS.md`, Tricky Part 4, for the exact rule.

## Folder map

See `PROJECT_CONTEXT.md` Section 3 for the full structure and Section 5
for why each design decision was made.

## Packages used

See `requirements.txt` (PyMuPDF, pytesseract, Pillow, requests) — kept
deliberately minimal, documented in `AI_USAGE_LOG.md`.
