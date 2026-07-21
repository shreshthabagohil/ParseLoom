"""
Flask-integration tests for Milestone 3's async job architecture in
app.py: POST /api/run returns a job_id fast, GET .../status polls
progress, GET .../result returns the final payload, and the whole thing
degrades safely under errors -- without ever making a real LLM call
(run_batch is mocked at the app.py import site so these tests are fast,
free, and deterministic).

Also covers the security properties this milestone is responsible for:
upload validation still works unchanged, filenames are sanitized (no path
traversal), unknown/expired job IDs get a generic 404, and errors never
leak a stack trace to the client.
"""
import io
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from src.jobs import JobStore  # noqa: E402
from src.models import ParsedResume  # noqa: E402


def _pdf_file(name="resume.pdf", content=b"%PDF-1.4 fake pdf bytes"):
    return (io.BytesIO(content), name)


def _fresh_job_store():
    """Each test gets an isolated store so job IDs/state from one test
    can't leak into another via the process-wide default store."""
    store = JobStore()
    return store


def _wait_for_terminal(client, job_id, timeout=5.0):
    """
    Polls /status until the job reaches "done" or "error", returning the
    final status payload. Every test that starts a background job MUST
    call this (inside its own `with patch(...)` block) before that block
    exits -- otherwise the background thread can still be running when the
    patch reverts app.run_batch/app.job_store back to the real ones, and a
    still-running thread's later lookups of those module globals will
    resolve to the REAL objects (making a real, unmocked LLM call and/or
    mutating the real shared job_store) racing against whatever the next
    test patches in. This bit us once during development -- see
    MILESTONE_LOG.md's Milestone 3 entry -- and this helper exists
    specifically so it can't happen again.
    """
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/run/{job_id}/status").get_json()
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.01)
    raise TimeoutError(f"job {job_id} did not reach a terminal state within {timeout}s")


def _fake_run_batch_factory(delay_per_resume=0.0):
    """Builds a stand-in for src.pipeline.run_batch that never touches the
    real LLM -- constructs deterministic ParsedResume objects instead, and
    still calls on_result per-resume (with an optional delay) so
    progressive-delivery behavior can be tested without real network
    calls."""

    def _fake_run_batch(paths, max_workers=None, on_result=None):
        resumes = []
        for path in paths:
            if delay_per_resume:
                time.sleep(delay_per_resume)
            resume = ParsedResume(
                file_name=os.path.basename(path),
                parse_status="Clean",
                full_name=f"Candidate for {os.path.basename(path)}",
                skills=["Python"],
            )
            if on_result is not None:
                on_result(path, resume)
            resumes.append(resume)
        return resumes

    return _fake_run_batch


def test_api_run_returns_job_id_fast_and_does_not_block():
    client = app_module.app.test_client()
    with patch("app.job_store", _fresh_job_store()), \
         patch("app.run_batch", _fake_run_batch_factory(delay_per_resume=0.05)):
        start = time.time()
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("a.pdf"), _pdf_file("b.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        elapsed = time.time() - start
        data = resp.get_json()
        # Drain the job to completion before the patch context exits (see
        # _wait_for_terminal's docstring) -- this doesn't weaken the
        # elapsed-time assertion below, it just prevents a leaked
        # background thread from outliving this test.
        _wait_for_terminal(client, data["job_id"])

    assert resp.status_code == 202
    assert "job_id" in data
    assert data["total"] == 2
    # Regression for Section 2 item 4: the request itself must return
    # almost immediately, not block for the ~0.1s (2 resumes x 0.05s) the
    # background job will actually take.
    assert elapsed < 0.05


def test_status_and_result_reflect_a_completed_job():
    store = _fresh_job_store()
    client = app_module.app.test_client()
    with patch("app.job_store", store), patch("app.run_batch", _fake_run_batch_factory()):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("a.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]

        # Background thread runs fast (no real delay in this test) but is
        # still async -- poll briefly until done rather than assuming
        # instant completion.
        status = _wait_for_terminal(client, job_id)

        assert status["status"] == "done"
        assert status["completed"] == 1
        assert status["total"] == 1

        result = client.get(f"/api/run/{job_id}/result")
        assert result.status_code == 200
        result_data = result.get_json()
        # Same top-level shape the old synchronous /api/run response had --
        # no schema drift for the frontend or a judge comparing to CLI output.
        assert set(result_data.keys()) >= {"jd", "result", "details", "llm_warning"}


def test_candidates_so_far_grows_progressively_before_job_finishes():
    """
    Direct regression test for the "8 should move forward and show,
    others join as they finish" requirement: individual candidates must
    become visible via /status before the whole batch completes, not only
    once everything is done.
    """
    store = _fresh_job_store()
    client = app_module.app.test_client()
    with patch("app.job_store", store), patch("app.run_batch", _fake_run_batch_factory(delay_per_resume=0.1)):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file(f"r{i}.pdf") for i in range(4)], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]

        # Poll shortly after submission -- with 4 resumes at 0.1s each
        # (sequential in this fake, run_batch's real concurrency isn't
        # under test here), the job should still be running but with at
        # least one candidate already visible.
        time.sleep(0.15)
        mid_status = client.get(f"/api/run/{job_id}/status").get_json()

        # Drain to completion before the patch context exits (see
        # _wait_for_terminal's docstring) -- the mid-run assertions below
        # are already captured in mid_status, so this doesn't affect them.
        _wait_for_terminal(client, job_id)

    assert mid_status["status"] == "running"
    assert 0 < mid_status["completed"] < 4  # some progress, not all-or-nothing


def test_unknown_job_id_returns_generic_404_for_status_and_result():
    client = app_module.app.test_client()
    with patch("app.job_store", _fresh_job_store()):
        status_resp = client.get("/api/run/does-not-exist/status")
        result_resp = client.get("/api/run/does-not-exist/result")

    assert status_resp.status_code == 404
    assert result_resp.status_code == 404
    # Generic message only -- no internal detail about why it's missing
    # (never existed vs. expired vs. malformed ID all look the same).
    assert "Unknown or expired job" in status_resp.get_json()["error"]


def test_result_returns_409_while_job_still_running():
    store = _fresh_job_store()
    client = app_module.app.test_client()
    with patch("app.job_store", store), patch("app.run_batch", _fake_run_batch_factory(delay_per_resume=0.2)):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("a.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]
        result_resp = client.get(f"/api/run/{job_id}/result")
        # Drain to completion before the patch context exits (see
        # _wait_for_terminal's docstring) -- captured status_code above
        # already reflects the mid-run 409, unaffected by draining after.
        _wait_for_terminal(client, job_id)

    assert result_resp.status_code == 409


def test_job_error_state_never_leaks_a_traceback_to_the_client():
    store = _fresh_job_store()
    client = app_module.app.test_client()

    def _exploding_run_batch(paths, max_workers=None, on_result=None):
        raise RuntimeError("simulated internal crash with a secret file path /etc/shadow")

    with patch("app.job_store", store), patch("app.run_batch", _exploding_run_batch):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("a.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]
        status = _wait_for_terminal(client, job_id)
        result_resp = client.get(f"/api/run/{job_id}/result")

    assert status["status"] == "error"
    assert result_resp.status_code == 500
    error_message = result_resp.get_json()["error"]
    assert "secret file path" not in error_message
    assert "/etc/shadow" not in error_message
    assert "RuntimeError" not in error_message


def test_upload_validation_unchanged_no_files():
    client = app_module.app.test_client()
    resp = client.post("/api/run", data={"jd": "frontend"}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "No resumes uploaded" in resp.get_json()["error"]


def test_upload_validation_unchanged_too_many_files():
    client = app_module.app.test_client()
    files = [_pdf_file(f"r{i}.pdf") for i in range(app_module.MAX_FILES_PER_REQUEST + 1)]
    resp = client.post(
        "/api/run", data={"resumes": files, "jd": "frontend"}, content_type="multipart/form-data"
    )
    assert resp.status_code == 400
    assert "Too many files" in resp.get_json()["error"]


def test_upload_validation_unchanged_missing_jd():
    client = app_module.app.test_client()
    resp = client.post(
        "/api/run", data={"resumes": [_pdf_file()]}, content_type="multipart/form-data"
    )
    assert resp.status_code == 400
    assert "No job description" in resp.get_json()["error"]


def test_non_pdf_files_are_silently_skipped_not_processed():
    client = app_module.app.test_client()
    with patch("app.job_store", _fresh_job_store()), patch("app.run_batch", _fake_run_batch_factory()):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("resume.pdf"), _pdf_file("not_a_resume.exe")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        _wait_for_terminal(client, resp.get_json()["job_id"])
    assert resp.status_code == 202
    assert resp.get_json()["total"] == 1  # only the .pdf counted


def test_malicious_filename_is_sanitized_no_path_traversal(tmp_path):
    """
    Security regression: a filename containing path-traversal sequences
    must never let a saved file escape the generated temp directory.
    werkzeug's secure_filename() is what's relied on here -- this test
    confirms the file that actually lands on disk is inside tmp_dir, with
    no ".." component surviving.
    """
    captured_paths = []

    def _capturing_run_batch(paths, max_workers=None, on_result=None):
        captured_paths.extend(paths)
        return [ParsedResume(file_name=os.path.basename(p), parse_status="Clean") for p in paths]

    client = app_module.app.test_client()
    with patch("app.job_store", _fresh_job_store()), patch("app.run_batch", _capturing_run_batch):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("../../../../etc/passwd.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]
        _wait_for_terminal(client, job_id)

    assert len(captured_paths) == 1
    saved_path = captured_paths[0]
    # werkzeug's secure_filename() collapses "../../../../etc/passwd.pdf"
    # into a flat filename (e.g. "etc_.pdf") with every path separator and
    # ".." component stripped -- the real security property is that no
    # directory traversal survives, not that the word "etc" disappears
    # entirely (it's allowed to remain as harmless flattened text).
    assert ".." not in saved_path
    saved_dir = os.path.dirname(saved_path)
    # The saved file must live directly inside a parseloom_job_ temp dir --
    # i.e. its directory component is exactly the generated tmp_dir, with
    # no extra path segments smuggled in via the filename.
    assert "parseloom_job_" in saved_dir
    assert os.path.basename(saved_path).count(os.sep) == 0
    assert "/" not in os.path.basename(saved_path)
