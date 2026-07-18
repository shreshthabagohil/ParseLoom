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

Verified against real data: 31 of 54 real resumes triggered genuine
two-column splitting, with coherent (non-interleaved) output. The known
failure case above was also deliberately tested with a synthetic
full-width-banner resume; it caused imperfect ordering but no data
loss — the limitation is real but not catastrophic in practice.

## Tricky Part 2 — The scanned resume

After standard text extraction, we count the words returned. If it's
below 50, we treat the file as a scan candidate: each page is rasterized
via PyMuPDF at 300 DPI and passed to pytesseract for OCR. If OCR
recovers usable text, we proceed with that as the resume's text and mark
it as OCR-derived, which caps its confidence lower than a clean text
extraction. If OCR still yields under 50 words, we mark the parse as
Failed with an explicit note, rather than guessing at a score from
almost nothing.

Verified against a genuine image-only PDF (no text layer at all, not
just a low-text one): OCR triggered correctly, recovered a usable CGPA
and skill set, and was correctly capped at Partial confidence. None of
the real 54-resume dataset happened to contain an actual scanned
resume, so this path is confirmed working but only on a synthetic
example, not a real one from the event's dataset.

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

Verified against real data: 114 real partial-match instances and 6 real
implicit-match instances across the 54-resume dataset (implicit
matching is genuine but rare in practice). The extraction prompt also
includes explicit instructions to treat resume text as untrusted data,
never as commands to follow — tested against a real prompt-injection
attempt (a fake "SYSTEM OVERRIDE" instruction embedded in resume text
claiming a perfect CGPA and skill set); the model correctly ignored it
and extracted only the genuinely present content. Relevant because this
is a resume *screening* tool — a candidate has direct incentive to try
exactly this.

## Tricky Part 4 — Parse quality affects score confidence

Confidence is derived directly from parse status, not just from how the
scoring math turns out. A Clean parse can reach High confidence. A
Partial parse is hard-capped at Medium, regardless of how strong the
data that *did* extract looks — because a strong partial score is still
built on incomplete information. A Failed parse produces no numeric
score at all: only a flag and a recommendation for human review. This
rule lives in a single function in the scoring engine so it can't be
silently skipped by a code path that forgets to check it.

Verified against real data: 54/54 real resumes reached Clean status, so
this rule's Partial/Failed branches were confirmed via synthetic
edge cases instead (a genuinely too-sparse resume, a corrupted file, an
empty file, and an OCR-derived resume all correctly hit the right
branch — see PROJECT_CONTEXT.md Section 11.5).
