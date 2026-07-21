"""
Flask web front end for the ParseLoom engine -- Bonus A. Thin wrapper
only: every route calls the exact same src/ functions main.py calls.
No new parsing/scoring logic here, ever (see WEB_APP_PLAN.md Section 6).

Run: python3 app.py   (dev server, http://127.0.0.1:5000)
"""
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from dataclasses import asdict
from io import BytesIO

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parseloom")

from src.env_loader import load_env  # noqa: E402

load_env()

from src import history, jd_loader  # noqa: E402
from src.jobs import job_store  # noqa: E402
from src.matching.scorer import _completeness_fraction  # noqa: E402
from src.matching.scorer import _signal_conflict_adjustment  # noqa: E402
from src.matching.scorer import score_candidate  # noqa: E402
from src.matching.shortlist import build_shortlist  # noqa: E402
from src.matching.skill_matcher import build_evidence, score_skill_list  # noqa: E402
from src.output.xlsx_export import build_workbook, workbook_to_bytes  # noqa: E402
from src.pipeline import run_batch, summarize_llm_failures  # noqa: E402

app = Flask(__name__)
# Security (WEB_APP_PLAN.md Section 5): cap total upload size and
# reject anything obviously too large before it ever reaches the LLM
# call budget.
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB total per request
# Explicit, not implied by debug mode: template changes (e.g. more
# Fable/Stitch iterations) should still show up on refresh without a
# server restart, without needing Werkzeug's debug=True (see the
# debug=False security fix further down).
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.after_request
def _add_security_headers(response):
    """
    Baseline HTTP security headers, added during the Milestone 3 security
    audit -- cheap, zero functional risk, real hardening against a class
    of attacks this app had no opinion on before:
    - X-Content-Type-Options: nosniff -- stops a browser from guessing a
      response's content type and executing an upload's content as
      script/HTML if it's ever reflected somewhere unexpected.
    - X-Frame-Options: DENY -- this app has no legitimate reason to be
      embedded in another site's iframe; denying it closes a clickjacking
      vector for free.
    - Referrer-Policy: same-origin -- avoids leaking this app's URLs
      (which can include job_id-bearing paths) to third-party sites via
      the Referer header if a user ever clicks an outbound link.
    Not added: a Content-Security-Policy -- this app currently loads
    external fonts (see templates/index.html's Google Fonts links), and a
    real CSP needs to be written deliberately against that specific
    external surface, not bolted on generically. Left for the later UI/UX
    phase once the final set of external resources is locked in.
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


ALLOWED_EXTENSION = ".pdf"
# Milestone 3: since /api/run no longer runs the batch synchronously
# (upload -> save -> return job_id is now the only work the request itself
# does), this cap is re-justified purely as an upload-sanity/resource limit,
# not a request-timeout avoidance measure. Raised from 60 to 80 -- the real
# event dataset is 54 resumes and the stated target is "up to 40," so 80
# leaves real headroom while still bounding a single request's worst-case
# LLM-quota exposure (each file triggers one real LLM call once processed).
MAX_FILES_PER_REQUEST = 80

# Milestone 4: the frontend generates this client-side (crypto.randomUUID(),
# stored in localStorage) -- it is NOT a login/auth token, just a random
# per-browser identifier used to scope run history so one visitor can't
# browse another visitor's past uploads (see src/history.py's module
# docstring). Validated server-side before ever being used in a query or
# stored on disk: must look like a real generated ID, not arbitrary
# attacker-supplied text.
CLIENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


def _clean_client_id(raw: str | None) -> str | None:
    if not raw or not CLIENT_ID_PATTERN.match(raw):
        return None
    return raw


def _build_candidate_details(resumes: list, jd) -> dict:
    """
    Full per-candidate detail for the web UI's expand-on-click view --
    deliberately NOT part of shortlist.py/build_shortlist, which is the
    CLI's canonical, already-documented output shape. This is web-only,
    additive, computed here (no extra LLM calls -- skill matching is a
    local vocab/text pass, same functions scorer.py already calls
    internally). Extracted into its own function (previously inline in
    api_run) so both the old synchronous path's logic and the new
    background-job path (Milestone 3) call exactly one implementation.
    """
    details = {}
    for r in resumes:
        if r.parse_status == "Failed":
            continue
        vocab_hits, evidence_text = build_evidence(
            r.raw_text,
            {
                "skills": r.skills,
                "projects": r.projects,
                "experience": r.experience,
                "certifications": r.certifications,
            },
        )
        required_avg, required_matches = score_skill_list(jd.required_skills, vocab_hits, evidence_text)
        preferred_avg, preferred_matches = score_skill_list(jd.preferred_skills, vocab_hits, evidence_text)

        # Score-transparency addition: the exact same numbers
        # score_candidate() computes internally, surfaced here so the
        # candidate detail page can show the formula with real numbers
        # plugged in instead of asking the user to trust a single output
        # number. Reuses scorer.py's own (underscore-prefixed but
        # same-package, not re-implemented) helper functions -- so this
        # can never drift from what actually produced the score, by
        # construction.
        skill_subscore = round(required_avg * 70 + preferred_avg * 30, 1)
        signal_delta, conflict_notes = _signal_conflict_adjustment(r)
        completeness = _completeness_fraction(r)

        details[r.file_name] = {
            "college": r.college,
            "degree_branch": r.degree_branch,
            "graduation_year": r.graduation_year,
            "cgpa_10pt": r.cgpa_10pt,
            "cgpa_source_format": r.cgpa_source_format,
            "skills": r.skills,
            "projects": r.projects,
            "experience": r.experience,
            "certifications": r.certifications,
            "required_skill_matches": required_matches,
            "preferred_skill_matches": preferred_matches,
            "parse_notes": r.parse_notes,
            # Milestone 1: surfaced on the detail page too, not just the
            # summary card -- a judge/user drilling into one candidate's
            # "why" must see this was a provider failure, not thin resume
            # content, at every level of detail, not just the top-level
            # list view.
            "llm_call_failed": r.llm_call_failed,
            "llm_failure_reason": r.llm_failure_reason,
            "score_breakdown": {
                "required_avg": round(required_avg, 3),
                "preferred_avg": round(preferred_avg, 3),
                "skill_subscore": skill_subscore,
                "signal_conflict_delta": signal_delta,
                "signal_conflict_notes": conflict_notes,
                "completeness_fraction": round(completeness, 3),
            },
        }
    return details


def _candidate_progress_row(score) -> dict:
    """The lightweight shape shown in /api/run/<job_id>/status while a job
    is still running -- deliberately smaller than a full shortlist row (no
    rank yet, since ranking only makes sense once the whole batch is
    scored), just enough for the frontend to render a card as each
    candidate finishes."""
    return {
        "file": score.candidate_file,
        "name": score.candidate_name,
        "score": score.score,
        "confidence": score.confidence,
        "parse_quality": score.parse_quality,
        "llm_call_failed": score.llm_call_failed,
    }


def _execute_job(job_id: str, saved_paths: list, jd, tmp_dir: str, client_id: str | None) -> None:
    """
    Runs in a background thread, started by api_run() right after it
    returns the job_id -- this is what makes /api/run itself fast (upload
    + validate + return, no LLM calls on the request thread) and what
    lets the browser poll for progress instead of blocking on the whole
    batch (Milestone 3 / Section 2 item 4).

    Security note: the `finally` block below deletes `tmp_dir` (and every
    uploaded resume PDF inside it) unconditionally, whether this job
    succeeds, partially fails, or crashes outright. Uploaded resumes --
    real people's PII -- must never linger on disk longer than the job
    that needs them, regardless of how that job ends.
    """
    try:
        def _on_result(path, resume):
            # Fired the moment each individual resume finishes, from
            # inside run_batch's worker pool -- this is what lets
            # /api/run/<job_id>/status show real, incrementally-arriving
            # progress rather than an all-or-nothing wait.
            score = score_candidate(resume, jd)
            job_store.append_candidate(job_id, _candidate_progress_row(score))

        resumes = run_batch(saved_paths, on_result=_on_result)

        results = [score_candidate(r, jd) for r in resumes]
        shortlist_data = build_shortlist(results, jd)
        details = _build_candidate_details(resumes, jd)
        llm_warning = summarize_llm_failures(resumes)
        result_payload = {"jd": jd.role, "result": shortlist_data, "details": details, "llm_warning": llm_warning}

        # Security ordering, deliberate: clean up the uploaded files BEFORE
        # marking the job done, not in a `finally` block that runs after.
        # A `finally`-based cleanup would still delete the files
        # eventually, but a poller could observe status="done" in the
        # small window before that `finally` block actually executes --
        # meaning "done" would not be a reliable guarantee that the
        # uploaded PII is already gone. Cleaning up first makes "done"
        # (or "error", same reasoning below) mean exactly that.
        shutil.rmtree(tmp_dir, ignore_errors=True)

        # Milestone 4: persist for later browsing, scoped to the
        # submitting browser's client_id (see src/history.py's module
        # docstring for why this is per-client, not global). Only
        # attempted if the client actually sent one -- an older/cached
        # frontend that hasn't picked up the client_id change yet still
        # works exactly as before, it just won't show up in "Past Runs."
        #
        # Ordering, deliberate, same reasoning as the tmp_dir cleanup
        # above: this must happen BEFORE job_store.mark_done(), not after.
        # mark_done() is what makes status="done" visible to a poller, and
        # a real (not hypothetical) race was caught by the full test suite:
        # a fast poller could see "done" and immediately GET
        # /api/runs/<job_id> before this line had run, getting a 404 for a
        # run that in fact succeeded. Persisting first makes "done" mean
        # "this run's history entry, if any, already exists."
        if client_id:
            history.save_run(job_id, client_id, jd.role, len(saved_paths), result_payload)

        job_store.mark_done(job_id, result_payload)
    except Exception:  # noqa: BLE001
        # Same security/robustness pattern as every other except-block in
        # this file: log the real detail server-side, never let a raw
        # exception or stack trace reach the client (there's no request
        # context left here to respond to anyway -- this becomes the
        # job's stored error_message, read later via /api/run/<id>/result).
        logger.exception("Job %s failed unexpectedly", job_id)
        # Same ordering guarantee as the success path above -- cleanup
        # happens before the terminal "error" status becomes visible to a
        # poller, not after.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        job_store.mark_error(job_id, "Something went wrong processing this batch. Check the server log for detail.")


@app.route("/")
def index():
    jd_options = [{"key": k, "role": jd_loader.load(k).role} for k in jd_loader.all_known_jd_keys()]
    return render_template("index.html", jd_options=jd_options)


@app.route("/api/jds")
def api_jds():
    jd_options = [asdict(jd_loader.load(k)) | {"key": k} for k in jd_loader.all_known_jd_keys()]
    return jsonify(jd_options)


@app.route("/api/jd/parse-text", methods=["POST"])
def api_parse_jd_text():
    text = request.json.get("text", "") if request.is_json else request.form.get("text", "")
    if not text or not text.strip():
        return jsonify({"error": "No JD text provided."}), 400
    try:
        jd = jd_loader.load(text)
    except Exception:  # noqa: BLE001
        # Security fix: the raw exception was being sent straight to the
        # browser. str(exc) on most exceptions is just a message, not a
        # full traceback, but there's no guarantee some future exception
        # type (or a nested one) doesn't include more than intended --
        # log the real detail server-side, return a generic message to
        # the client, same pattern used for the API-key-leak fix in
        # src/ai_client.py.
        logger.exception("JD text parsing failed")
        return jsonify({"error": "Could not parse this job description. Check the server log for detail."}), 400
    return jsonify(asdict(jd))


@app.route("/api/run", methods=["POST"])
def api_run():
    """
    Milestone 3: no longer runs the batch synchronously. Validates the
    upload, saves files, starts a background thread, and returns a job_id
    immediately -- the actual parsing/scoring happens off the request
    thread, polled via /api/run/<job_id>/status and
    /api/run/<job_id>/result below. This is what fixes Section 2 item 4
    (a slow batch used to block the whole HTTP request, with real risk of
    hitting a reverse-proxy timeout on a hosted deploy) and item 3 (fixed
    concurrency regardless of batch size -- see pipeline.py's run_batch).
    """
    try:
        files = request.files.getlist("resumes")
        if not files:
            return jsonify({"error": "No resumes uploaded."}), 400

        if len(files) > MAX_FILES_PER_REQUEST:
            return jsonify({"error": f"Too many files -- max {MAX_FILES_PER_REQUEST} per request."}), 400

        jd_input = request.form.get("jd", "").strip()
        if not jd_input:
            return jsonify({"error": "No job description selected."}), 400

        # Optional -- an older cached frontend or a direct API caller that
        # doesn't send one still works exactly as before, it just won't
        # get a "Past Runs" entry for this run (history.save_run is
        # already a no-op-safe call in that case, see _execute_job).
        client_id = _clean_client_id(request.form.get("client_id"))

        try:
            jd = jd_loader.load(jd_input)
        except Exception:  # noqa: BLE001
            logger.exception("JD loading failed in /api/run")
            return jsonify({"error": "Could not load this job description. Check the server log for detail."}), 400

        # Security: never trust the client filename directly -- every saved
        # file gets either werkzeug's secure_filename() or a fresh UUID
        # name, and lives under a directory this process generated itself
        # (tempfile.mkdtemp), never a client-controlled path. Unlike the
        # old synchronous version, this can't use `with
        # tempfile.TemporaryDirectory()` -- that would delete the directory
        # the instant this request handler returns, which is now BEFORE
        # the background job has even started reading the files. Cleanup
        # is instead the background job's explicit responsibility (see
        # _execute_job's `finally` block), which is the only place that
        # actually knows when it's safe to delete.
        tmp_dir = tempfile.mkdtemp(prefix="parseloom_job_")
        saved_paths = []
        for f in files:
            if not f.filename.lower().endswith(ALLOWED_EXTENSION):
                continue  # silently skip non-PDFs, matches main.py's glob("*.pdf") behavior
            safe_name = secure_filename(f.filename) or f"{uuid.uuid4().hex}.pdf"
            saved_path = os.path.join(tmp_dir, safe_name)
            f.save(saved_path)
            saved_paths.append(saved_path)

        if not saved_paths:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return jsonify({"error": "No valid .pdf files in the upload."}), 400

        job_id = job_store.create(total=len(saved_paths))
        worker_thread = threading.Thread(
            target=_execute_job,
            args=(job_id, saved_paths, jd, tmp_dir, client_id),
            daemon=True,  # never blocks process shutdown
        )
        worker_thread.start()

        return jsonify({"job_id": job_id, "total": len(saved_paths)}), 202

    except HTTPException:
        # Milestone 7 fix: a blind `except Exception` below this point was
        # also catching Werkzeug's own HTTP-level exceptions -- e.g.
        # RequestEntityTooLarge, raised by request.files itself the moment
        # an upload exceeds MAX_CONTENT_LENGTH -- and converting a correct,
        # specific 413 into a misleading generic 500. HTTPException
        # instances already know their own correct status code and message;
        # re-raise so Flask's normal error handling returns them as-is.
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error starting a batch in /api/run")
        return jsonify({"error": "Something went wrong starting this batch. Check the server log for detail."}), 500


@app.route("/api/run/<job_id>/status")
def api_run_status(job_id):
    """
    Polled by the frontend every ~1.5s while a job runs. Deliberately
    returns only progress-shaped data (candidates_so_far via
    _candidate_progress_row) -- the full detail payload is only available
    from /api/run/<job_id>/result once the job is actually done, keeping
    each poll response small.
    """
    job = job_store.get(job_id)
    if job is None:
        # Security: identical response whether the job_id is malformed,
        # never existed, or existed but aged out of the TTL -- an attacker
        # (or just a stale browser tab) gets no signal distinguishing
        # these cases.
        return jsonify({"error": "Unknown or expired job."}), 404
    return jsonify(
        {
            "status": job.status,
            "completed": job.completed,
            "total": job.total,
            "candidates_so_far": job.candidates_so_far,
        }
    )


@app.route("/api/run/<job_id>/result")
def api_run_result(job_id):
    job = job_store.get(job_id)
    if job is None:
        return jsonify({"error": "Unknown or expired job."}), 404
    if job.status == "running":
        return jsonify({"error": "Job is still running."}), 409
    if job.status == "error":
        return jsonify({"error": job.error_message or "Job failed."}), 500
    return jsonify(job.result)


@app.route("/api/run/<job_id>/export.xlsx")
def api_run_export_xlsx(job_id):
    """
    Downloads a completed run's full data (Summary / Shortlist / Reserve /
    Needs Review, with per-candidate detail) as a real, editable .xlsx
    file -- the user can open it in Excel/Sheets and sort, filter, or edit
    it however they want, independent of this web app. Reuses the exact
    same `job.result` payload /api/run/<job_id>/result already returns as
    JSON -- src/output/xlsx_export.py only serializes it differently, no
    new scoring/parsing logic (WEB_APP_PLAN.md Section 6).

    Same status-code contract as /result (404 unknown/expired, 409 still
    running, 500 if the job itself failed) -- a client that already knows
    how to handle /result's responses doesn't need new logic for this.
    """
    job = job_store.get(job_id)
    if job is None:
        return jsonify({"error": "Unknown or expired job."}), 404
    if job.status == "running":
        return jsonify({"error": "Job is still running."}), 409
    if job.status == "error":
        return jsonify({"error": job.error_message or "Job failed."}), 500

    try:
        # Milestone 5.5: gives every Shortlist/Reserve row a real, working
        # "Details Link" column -- request.host_url (e.g.
        # "http://127.0.0.1:5000/") plus this job_id is everything
        # candidate.html needs to fetch this specific candidate's data
        # server-side (see candidate.html's ?job_id= handling), so the link
        # works for anyone who opens it while the job is still in
        # job_store's TTL window, not just this browser tab.
        link_params = {"base_url": request.host_url, "job_id": job_id}
        workbook = build_workbook(job.result, link_params=link_params)
        xlsx_bytes = workbook_to_bytes(workbook)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build .xlsx export for job %s", job_id)
        return jsonify({"error": "Could not build the Excel export. Check the server log for detail."}), 500

    # Security: the download filename is built from the JD role name,
    # which came from data/jds.json or an LLM-extracted free-text JD --
    # never trust it directly as a filename. secure_filename() strips
    # anything that isn't a safe filename character (including attempts at
    # HTTP header injection via the Content-Disposition header).
    role_slug = secure_filename((job.result or {}).get("jd") or "results") or "results"
    filename = f"parseloom_{role_slug}_{job_id[:8]}.xlsx"

    return send_file(
        BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/api/runs")
def api_list_runs():
    """
    Lists this browser's own past runs (Milestone 4), newest first --
    lets the frontend render a "Past Runs" list the user can click back
    into days later, per the user's explicit request ("that can be either
    from 5 days ago or 10 days ago or any JD").

    Scoped strictly to the client_id the browser sends -- never a global
    listing. An absent/invalid client_id (e.g. a fresh visitor who hasn't
    generated one yet) just gets an empty list back, not an error.
    """
    client_id = _clean_client_id(request.args.get("client_id"))
    if not client_id:
        return jsonify({"runs": []})
    runs = history.list_runs_for_client(client_id)
    return jsonify({"runs": runs})


@app.route("/api/runs/<run_id>")
def api_get_run(run_id):
    """
    Reopens one past run's full result payload -- same shape /api/run/<job_id>/result
    already returns, so the frontend's existing renderResults() can be reused
    unchanged for historical runs too.

    Security: ownership is enforced by history.get_run_for_client(), which
    requires BOTH the correct run_id AND the requesting client_id to match
    what was stored -- knowing/guessing a run_id alone (already a UUID4)
    is not enough to read someone else's data. A missing/invalid client_id
    or an ownership mismatch both return the same 404 (not a 403), so a
    client can't use the response to probe whether a given run_id exists
    under a different owner.
    """
    client_id = _clean_client_id(request.args.get("client_id"))
    if not client_id:
        return jsonify({"error": "Unknown run."}), 404
    result = history.get_run_for_client(run_id, client_id)
    if result is None:
        return jsonify({"error": "Unknown run."}), 404
    return jsonify(result)


@app.route("/api/runs/<run_id>/export.xlsx")
def api_export_run_xlsx(run_id):
    """
    Same Excel export as /api/run/<job_id>/export.xlsx, but for a past run
    read back out of persistent history rather than the in-memory job
    store. Reuses the exact same build_workbook()/workbook_to_bytes() --
    no new scoring/parsing/export logic (WEB_APP_PLAN.md Section 6).
    Same ownership enforcement as GET /api/runs/<run_id> above.
    """
    client_id = _clean_client_id(request.args.get("client_id"))
    if not client_id:
        return jsonify({"error": "Unknown run."}), 404
    result = history.get_run_for_client(run_id, client_id)
    if result is None:
        return jsonify({"error": "Unknown run."}), 404

    try:
        # Milestone 5.5: same "Details Link" column as the live-job export
        # route above, but pointed at the historical-run lookup instead
        # (?run_id=&client_id=, matching how the frontend's own "Past Runs"
        # list already fetches this same run -- see candidate.html's
        # ?run_id= handling). client_id ends up embedded in the exported
        # file's link, same exposure level the existing "Past Runs" export
        # button's URL already has -- not a new risk this milestone
        # introduces.
        link_params = {"base_url": request.host_url, "run_id": run_id, "client_id": client_id}
        workbook = build_workbook(result, link_params=link_params)
        xlsx_bytes = workbook_to_bytes(workbook)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build .xlsx export for historical run %s", run_id)
        return jsonify({"error": "Could not build the Excel export. Check the server log for detail."}), 500

    role_slug = secure_filename((result or {}).get("jd") or "results") or "results"
    filename = f"parseloom_{role_slug}_{run_id[:8]}.xlsx"

    return send_file(
        BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/results")
def results_page():
    return render_template("results.html")


@app.route("/candidate")
def candidate_page():
    # Deliberately stateless, like every other route here: no server-side
    # session or database to look candidates up by ID. The browser already
    # has the full result payload in memory right after a run -- this
    # page's JS reads that same data back out of localStorage (set at
    # render time, see index.html) and picks out the one candidate whose
    # filename matches the ?file= query param. Replaces the earlier
    # in-card expand panel, which broke on real data: nesting a 2-column
    # skill breakdown inside an already-narrow card caused real horizontal
    # overflow, cutting text off mid-word. A dedicated page gets the full
    # viewport to lay out in, so that class of bug can't recur here.
    return render_template("candidate.html")


if __name__ == "__main__":
    # Security fix: debug=True enables Werkzeug's interactive debugger,
    # which renders full stack tracebacks (and, if ever reached, a
    # PIN-protected but still real remote-code-execution console) in the
    # browser on any unhandled error. Fine for isolated local dev, risky
    # on a hackathon venue's shared network. debug=False here;
    # TEMPLATES_AUTO_RELOAD above keeps template edits picking up live
    # without needing debug mode for it.
    #
    # use_reloader=True is independent of debug -- it restarts the
    # Python process automatically when app.py (or anything under src/)
    # changes, WITHOUT turning on the interactive debugger above.
    #
    # threaded=True (new, Milestone 3): with background jobs now running
    # in their own threads while the Flask app keeps serving requests
    # (status polls, new job submissions), the dev server must be able to
    # handle more than one request at a time -- without this, a slow
    # request could block a status poll behind it even though the actual
    # batch processing happens off-thread already.
    app.run(debug=False, use_reloader=True, threaded=True, port=5000)
