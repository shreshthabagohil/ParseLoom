"""
Milestone 7: forced-unhandled-exception test. Every existing except-block
in app.py already follows the "log real detail server-side, return a
generic message to the client" pattern for the specific failure modes
found so far (bad JD text, a crashed job, a broken .xlsx export, the
Milestone-7 path-leak-in-pdf_reader fix, etc.) -- but until now nothing
proved that an *arbitrary*, previously-unseen exception raised deep inside
the pipeline is caught by that same generic net, rather than a stack
trace or an internal file path leaking out because this particular
exception type wasn't one of the ones a developer thought to handle.

Uses a test double that raises a deliberately sensitive, made-up exception
(embedding a fake file path and a fake secret-looking string) from inside
run_batch -- if the generic-message guarantee ever has a gap, this is the
kind of exception that would slip through it.
"""
import io
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from src.jobs import JobStore  # noqa: E402

SENSITIVE_PATH = "/home/deploy/secret_config/db_credentials.yaml"
SENSITIVE_SECRET = "sk-FAKE-SECRET-VALUE-1234567890"


def _pdf_file(name="resume.pdf", content=b"%PDF-1.4 fake pdf bytes"):
    return (io.BytesIO(content), name)


def _fresh_job_store():
    return JobStore()


def _wait_for_terminal(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/run/{job_id}/status").get_json()
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.01)
    raise TimeoutError(f"job {job_id} did not reach a terminal state within {timeout}s")


def _raising_run_batch(paths, max_workers=None, on_result=None):
    """A previously-unseen exception type (not LLMError, not any exception
    app.py's except-blocks were written with in mind) -- deliberately
    embeds a fake path and a fake secret in its message, the way a real
    unexpected exception (e.g. a third-party library's internal error)
    plausibly could."""
    raise RuntimeError(
        f"unexpected internal failure while reading {SENSITIVE_PATH} "
        f"(auth token was {SENSITIVE_SECRET})"
    )


def test_forced_unhandled_exception_in_background_job_never_leaks_detail():
    client = app_module.app.test_client()
    store = _fresh_job_store()
    with patch("app.job_store", store), patch("app.run_batch", _raising_run_batch):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("a.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )
        job_id = resp.get_json()["job_id"]
        status = _wait_for_terminal(client, job_id)

        assert status["status"] == "error"

        result_resp = client.get(f"/api/run/{job_id}/result")
        assert result_resp.status_code == 500
        body = result_resp.get_json()

    # The client-facing payload (both the /status and /result views) must
    # be the pre-written generic message only -- never the raw exception
    # text, never a stack trace, never the fake path/secret embedded above.
    full_text = str(status) + str(body)
    assert SENSITIVE_PATH not in full_text
    assert SENSITIVE_SECRET not in full_text
    assert "Traceback" not in full_text
    assert "RuntimeError" not in full_text
    assert "Something went wrong processing this batch" in body["error"]


def test_forced_unhandled_exception_starting_a_batch_returns_generic_500():
    """Same guarantee, but for an exception raised on the request thread
    itself (before the background job even starts) -- e.g. a bug in
    job_store.create() -- covered by api_run()'s own outer except-block,
    which is distinct code from _execute_job()'s and needs its own proof."""
    client = app_module.app.test_client()

    def _raising_create(total):
        raise RuntimeError(f"boom while touching {SENSITIVE_PATH} (token={SENSITIVE_SECRET})")

    with patch("app.job_store.create", _raising_create):
        resp = client.post(
            "/api/run",
            data={"resumes": [_pdf_file("a.pdf")], "jd": "frontend"},
            content_type="multipart/form-data",
        )

    assert resp.status_code == 500
    body_text = resp.get_data(as_text=True)
    assert SENSITIVE_PATH not in body_text
    assert SENSITIVE_SECRET not in body_text
    assert "Traceback" not in body_text
    assert "RuntimeError" not in body_text
    assert "Something went wrong starting this batch" in body_text
