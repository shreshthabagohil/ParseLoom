# Design Decisions — InternLoom Resume Shortlisting Engine

(Submission-required document. Drafted during pre-build planning —
confirm each paragraph still matches the actual implementation before
submitting; edit if reality diverged from the plan.)

## Tricky Part 1 — Multi-column layout

We use PyMuPDF's `page.get_text("blocks")` to get every text block on
the page along with its bounding box. We compute the horizontal
midpoint of each block and check whether the blocks cluster into two
clear groups — roughly left-of-center and right-of-center, with a gap
between them. When that pattern holds, we split the blocks into left and
right groups by x-position, sort each group top-to-bottom, and read the
left column fully before the right column. This avoids the default
reading-order bug where a two-column resume interleaves unrelated
content mid-sentence. Known failure case: a full-width header or name
banner that spans both columns can get pulled into whichever column it
overlaps more, and true three-column layouts aren't specifically
handled — they'll approximate as two.

## Tricky Part 2 — The scanned resume

After standard text extraction, we count the words returned. If it's
below 50, we treat the file as a scan candidate: each page is rasterized
via PyMuPDF at 300 DPI and passed to pytesseract for OCR. If OCR
recovers usable text, we proceed with that as the resume's text and mark
it as OCR-derived, which caps its confidence lower than a clean text
extraction. If OCR still yields under 50 words, we mark the parse as
Failed with an explicit note, rather than guessing at a score from
almost nothing.

## Tricky Part 3 — Skill extraction from unstructured text

We use both a deterministic pass and an LLM pass, not one or the other.
A curated vocabulary of skill terms and known synonyms (built from every
skill listed across the five job descriptions) is searched across the
resume's full text, not just a labeled "Skills" section — this catches
skills mentioned inline in project or experience descriptions. Separately,
we send the full resume text to an LLM with a structured-extraction
prompt asking for name, contact info, education, skills, projects,
experience, and certifications as JSON. The LLM pass does most of the
actual field extraction; the vocabulary pass exists to give skill matches
a second, auditable confidence signal that doesn't depend entirely on the
model's output. What this combination still misses: skills described
using terminology neither list recognizes — invented tool names, very
new or obscure technologies.

## Tricky Part 4 — Parse quality affects score confidence

Confidence is derived directly from parse status, not just from how the
scoring math turns out. A Clean parse can reach High confidence. A
Partial parse is hard-capped at Medium, regardless of how strong the
data that *did* extract looks — because a strong partial score is still
built on incomplete information. A Failed parse produces no numeric
score at all: only a flag and a recommendation for human review. This
rule lives in a single function in the scoring engine so it can't be
silently skipped by a code path that forgets to check it.
