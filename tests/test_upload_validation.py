"""
Milestone 7: explicit security-boundary tests for POST /api/run's upload
surface (WEB_APP_PLAN.md Section 5). These boundaries already existed in
app.py before this milestone (MAX_CONTENT_LENGTH, ALLOWED_EXTENSION,
MAX_FILES_PER_REQUEST, secure_filename) -- what didn't exist was a test
pinning each one down individually as a security guarantee, rather than
something that happened to work.

Does not make a real LLM call for the file-count/size/extension checks
(they're all rejected before any resume is ever parsed). The
fake-.pdf-extension-real-non-PDF-bytes case is deliberately run through the
REAL pipeline (not mocked run_batch) -- the whole point of that test is to
prove app.py doesn't need its own PDF-sniffing logic because
fitz.open() failing gracefully (already proven in Milestone 0 against
these exact fixture files) is sufficient, all the way from a real HTTP
upload through to a real, non-crashing "Failed" result.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from src.jobs import JobStore  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pdf_file(name="resume.pdf", content=b"%PDF-1.4 fake pdf bytes"):
    return (io.BytesIO(content), name)


def _fresh_job_store():
    return JobStore()


def _wait_for_terminal(client, job_id, timeout=15.0):
    import time

    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/run/{job_id}/status").get_json()
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.02)
    raise TimeoutError(f"job {job_id} did not reach a terminal state within {timeout}s")


def test_oversized_upload_rejected_before_any_processing():
    """Flask's MAX_CONTENT_LENGTH (25MB) should reject the request itself
    (413), before app.py's own route code ever runs -- confirms the config
    value is actually wired up, not just set and ignored."""
    client = app_module.app.test_client()
    oversized_content = b"%PDF-1.4 " + (b"0" * (26 * 1024 * 1024))  # 26MB > 25MB cap
    resp = client.post(
        "/api/run",
        data={"resumes": [_pdf_file("huge.pdf", oversized_content)], "jd": "frontend"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413


def test_wrong_extension_silently_skipped_not_processed():
    """A non-.pdf file must never reach the parsing pipeline -- matches
    main.py's glob("*.pdf") behavior. A batch of only non-PDF files
    produces a clean 400, not an attempt to parse them."""
    client = app_module.app.test_client()
    resp = client.post(
        "/api/run",
        data={
            "resumes": [(io.BytesIO(b"not a resume"), "resume.docx"), (io.BytesIO(b"data"), "resume.txt")],
            "jd": "frontend",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "No valid .pdf files" in resp.get_json()["error"]


def test_file_count_over_cap_rejected():
    """MAX_FILES_PER_REQUEST=80 is enforced before any file is saved to
    disk or parsed -- an over-cap batch is rejected outright, not silently
    truncated to the first 80."""
    client = app_module.app.test_client()
    files = [_pdf_file(f"r{i}.pdf") for i in range(81)]
    resp = client.post(
        "/api/run",
        data={"resumes": files, "jd": "frontend"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "Too many files" in resp.get_json()["error"]


def test_fake_pdf_extension_real_non_pdf_bytes_handled_gracefully_end_to_end():
    """A file named `fake.pdf` but containing non-PDF bytes passes the
    extension check (that's all app.py checks server-side before saving),
    then must be caught by fitz.open() failing gracefully downstream in the
    real pipeline -- not a crash, not a 500, not a hang. This is the
    explicit security-boundary test REBUILD_PLAN.md's Milestone 7 asks
    for: the existing graceful-failure behavior (already proven in
    Milestone 0 against these exact fixtures) now proven to hold through
    the full real HTTP upload -> background job -> result path, not just
    when parse_one_resume is called directly in a unit test.
    """
    client = app_module.app.test_client()
    with (Path(__file__).resolve().parent.parent / "data" / "mock_resumes" / "mock_corrupted_file.pdf").open("rb") as fh:
        corrupted_bytes = fh.read()

    store = _fresh_job_store()
    import app as app_module_ref

    original_store = app_module_ref.job_store
    app_module_ref.job_store = store
    try:
        resp = client.post(
            "/api/run",
            data={
                "resumes": [(io.BytesIO(corrupted_bytes), "fake.pdf")],
                "jd": "frontend",
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]
        status = _wait_for_terminal(client, job_id)
        assert status["status"] == "done"

        result = client.get(f"/api/run/{job_id}/result").get_json()
        needs_review = result["result"]["needs_review"]
        assert len(needs_review) == 1
        assert needs_review[0]["file"] == "fake.pdf"
        # No stack trace, no internal temp-file path -- same guarantee
        # test_no_path_leak.py already established for this exact scenario,
        # re-confirmed here through the real upload route rather than a
        # direct pdf_reader.extract() call.
        reason = needs_review[0]["reason"]
        assert "Traceback" not in reason
        assert "/tmp" not in reason
        assert "parseloom_job_" not in reason
    finally:
        app_module_ref.job_store = original_store
