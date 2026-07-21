"""
Security/PII-lifecycle test: an uploaded resume's temp directory must be
deleted once its job reaches a terminal state (done OR error) -- uploaded
resumes are real people's PII and must never linger on disk longer than
the job that needs them. This is tested with real filesystem operations
(no mocking of shutil/tempfile), only run_batch is faked to avoid a real
LLM call.
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from src.jobs import JobStore  # noqa: E402
from src.models import ParsedResume  # noqa: E402


def _pdf_bytes_file(name="resume.pdf"):
    import io

    return (io.BytesIO(b"%PDF-1.4 fake"), name)


def _wait_for_terminal_status(client, job_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/run/{job_id}/status").get_json()
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.01)
    raise TimeoutError("job did not reach a terminal state in time")


def test_temp_dir_is_deleted_after_successful_job():
    captured_dirs = []

    def _fake_run_batch(paths, max_workers=None, on_result=None):
        for p in paths:
            captured_dirs.append(os.path.dirname(p))
        return [ParsedResume(file_name=os.path.basename(p), parse_status="Clean") for p in paths]

    client = app_module.app.test_client()
    with patch("app.job_store", JobStore()), patch("app.run_batch", _fake_run_batch):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_bytes_file("a.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]
        status = _wait_for_terminal_status(client, job_id)

    assert status["status"] == "done"
    assert len(captured_dirs) == 1
    tmp_dir = captured_dirs[0]
    # The temp dir existed while the job ran (captured_dirs proves the
    # file was actually saved there); it must be gone now.
    assert not os.path.exists(tmp_dir)


def test_temp_dir_is_deleted_even_when_the_job_crashes():
    captured_dirs = []

    def _exploding_run_batch(paths, max_workers=None, on_result=None):
        for p in paths:
            captured_dirs.append(os.path.dirname(p))
        raise RuntimeError("simulated crash")

    client = app_module.app.test_client()
    with patch("app.job_store", JobStore()), patch("app.run_batch", _exploding_run_batch):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_bytes_file("a.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]
        status = _wait_for_terminal_status(client, job_id)

    assert status["status"] == "error"
    assert len(captured_dirs) == 1
    tmp_dir = captured_dirs[0]
    # Cleanup must happen on the error path too -- a crash must not leave
    # uploaded PII sitting on disk indefinitely.
    assert not os.path.exists(tmp_dir)
