# AI Usage Log

(Submission-required. Max 200 words. Draft below — trim/edit to match
what actually happened by the time you submit, don't leave it
aspirational.)

---

Used Claude (via Cowork/Antigravity) for architecture planning, the
column-detection and OCR-fallback design, the scoring formula, and most
of the Python implementation. Used [Codex/Gemini — fill in if you
actually switch tools] for [specific mechanical task, e.g. "writing the
skill vocabulary/synonym list" or "the CLI argument parsing"].

What I changed or built beyond what was generated: [fill in honestly —
e.g. "adjusted the CGPA-ambiguity threshold after testing against real
resumes in the dataset," or "rewrote the column-split logic after it
misclassified a resume with a full-width header"]. The scoring weights
(70/30 required/preferred split, the confidence-capping rule for partial
parses) were a deliberate design decision, not AI-suggested — documented
in DESIGN_DECISIONS.md.

---

Word count so far: ~110. Leave room to add specifics once the actual
build produces real examples of what you changed.
