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
AI_PROVIDER=openai        # or anthropic / gemini
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
```

## Run

```bash
python main.py --resumes data/real_resumes --jd frontend
python main.py --resumes data/real_resumes --all-jds
python main.py --resumes data/real_resumes --jd path/to/sixth_jd.json
```

Output is written to `output/sample_output.json` and
`output/parse_quality_report.md`.

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
