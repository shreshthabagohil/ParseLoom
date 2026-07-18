# AI Usage Log

(Submission-required. Max 200 words.)

---

Claude (via Antigravity and Cowork, this project's dual-tool workflow —
see PROJECT_CONTEXT.md) was used for architecture planning, the
column-detection/OCR-fallback/scoring-formula design, and most of the
Python implementation.

A separate Claude-in-Cowork session ran the engine against the real
54-resume dataset and read the actual output files rather than trusting
that the code looked right. This surfaced and fixed real bugs synthetic
testing hadn't caught: a Gemini response-truncation bug (missing
`maxOutputTokens`), a Gemini free-tier daily-quota wall requiring a Groq
fallback provider, a missing `llm_jd_extract.py` module and a
`Path.exists()` crash in the free-text JD loader, an API-key-leak vector
in error messages, a PII-redaction gap (only the first email/phone on a
resume was redacted, not all of them), and an accidentally-committed
cache file containing real students' PII that required a full git
history rewrite. A deterministic CGPA-extraction fallback and
prompt-injection hardening on the extraction prompt were also added and
verified against real and synthetic data.

The scoring weights (70/30 required/preferred split, the
confidence-capping rule for partial parses, the ±5 signal-conflict
adjustment) were deliberate design decisions, not AI-suggested —
documented in `DESIGN_DECISIONS.md`.

---

Word count: ~185.
