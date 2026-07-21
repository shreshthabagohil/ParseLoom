"""
Security regression test, added during Milestone 3's security audit: a
resume whose bytes aren't actually a valid PDF (wrong content, corrupted,
or truncated) must be handled gracefully AND must never leak the server's
internal temp-file path into any client-facing text. Found via a real,
non-mocked upload during the audit -- fitz.open()'s exception text
includes the full server-side path (e.g. "/tmp/parseloom_job_xyz/
fake.pdf"), which was flowing straight into parse_notes -> needs_review ->
the JSON response -> the browser. Fixed in src/extraction/pdf_reader.py;
this test exists so it can't silently regress.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extraction.pdf_reader import extract


def test_invalid_pdf_content_failure_note_never_contains_the_real_path(tmp_path):
    fake_pdf = tmp_path / "not_actually_a_pdf.pdf"
    fake_pdf.write_bytes(b"this is not valid PDF content at all")

    raw_text, method, notes = extract(str(fake_pdf))

    assert method == "failed"
    joined_notes = " ".join(notes)
    # The absolute temp path (tmp_path itself) must never appear in any
    # note returned to a caller -- only the bare filename is allowed.
    assert str(tmp_path) not in joined_notes
    assert "not_actually_a_pdf.pdf" in joined_notes  # filename itself is fine, client already knows it


def test_empty_file_failure_note_never_contains_the_real_path(tmp_path):
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"")

    raw_text, method, notes = extract(str(empty_pdf))

    assert method == "failed"
    joined_notes = " ".join(notes)
    assert str(tmp_path) not in joined_notes
