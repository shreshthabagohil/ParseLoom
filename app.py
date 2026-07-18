"""
Flask web front end for the ParseLoom engine -- Bonus A. Thin wrapper
only: every route calls the exact same src/ functions main.py calls.
No new parsing/scoring logic here, ever (see WEB_APP_PLAN.md Section 6).

Run: python3 app.py   (dev server, http://127.0.0.1:5000)
"""
import logging
import os
import tempfile
import uuid
from dataclasses import asdict

from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parseloom")

from src.env_loader import load_env

load_env()

from src import jd_loader  # noqa: E402
from src.ai_client import LLMError  # noqa: E402
from src.extraction.grade_normalizer import find_and_normalize_from_raw_text  # noqa: E402
from src.extraction.grade_normalizer import normalize as normalize_grade  # noqa: E402
from src.extraction.llm_extract import extract_structured_fields  # noqa: E402
from src.extraction.pdf_reader import extract  # noqa: E402
from src.extraction.pii_redact import extract_contact_and_redact  # noqa: E402
from src.matching.scorer import score_candidate  # noqa: E402
from src.matching.shortlist import build_shortlist  # noqa: E402
from src.models import ParsedResume  # noqa: E402

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

ALLOWED_EXTENSION = ".pdf"
# Security fix (found in the 2026-07-18 post-build review, wasn't caught
# when app.py was first written): no cap existed on the NUMBER of files
# per request, only total bytes. A request with many tiny PDFs could
# still slip under the 25MB cap while triggering one real LLM call per
# file -- a real cost/quota exhaustion vector, not just a hypothetical
# one (see the Gemini/Groq daily-quota incidents in PROJECT_CONTEXT.md
# Section 11).
MAX_FILES_PER_REQUEST = 20


def parse_one_resume(path: str) -> ParsedResume:
    """Same logic as main.py::parse_one_resume -- kept as one copy would
    require restructuring main.py's CLI-only imports; duplicated here
    deliberately with a comment rather than silently drifting. If you
    change scoring/extraction logic, change it in both places or (better)
    refactor main.py to expose this as an importable function."""
    file_name = os.path.basename(path)
    raw_text, method, notes = extract(path)
    word_count = len(raw_text.split())

    resume = ParsedResume(
        file_name=file_name,
        raw_text=raw_text,
        parse_method=method,
        parse_notes=list(notes),
        text_word_count=word_count,
    )

    if method == "failed":
        resume.parse_status = "Failed"
        return resume

    email, phone, redacted = extract_contact_and_redact(raw_text)
    resume.email = email
    resume.phone = phone

    try:
        fields = extract_structured_fields(redacted)
    except LLMError as exc:
        resume.parse_status = "Partial"
        resume.parse_notes.append(f"LLM extraction failed, falling back to partial signal: {exc}")
        return resume

    resume.full_name = fields.get("full_name")
    resume.college = fields.get("college")
    resume.degree_branch = fields.get("degree_branch")
    resume.graduation_year = fields.get("graduation_year")
    resume.skills = fields.get("skills") or []
    resume.projects = fields.get("projects") or []
    resume.experience = fields.get("experience") or []
    resume.certifications = fields.get("certifications") or []

    grade = normalize_grade(fields.get("cgpa_raw_text") or "")
    if grade.cgpa_10pt is None:
        fallback = find_and_normalize_from_raw_text(raw_text)
        if fallback.cgpa_10pt is not None:
            grade = fallback
            resume.parse_notes.append("CGPA recovered via deterministic fallback scan.")
    resume.cgpa_10pt = grade.cgpa_10pt
    resume.cgpa_source_format = grade.source_format
    if grade.note:
        resume.parse_notes.append(grade.note)

    missing_core = sum(1 for v in [resume.full_name, resume.cgpa_10pt] if v is None) + (0 if resume.skills else 1)
    resume.parse_status = "Partial" if (method == "ocr" or missing_core >= 2) else "Clean"
    return resume


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
    except Exception as exc:  # noqa: BLE001
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
    try:
        files = request.files.getlist("resumes")
        if not files:
            return jsonify({"error": "No resumes uploaded."}), 400

        if len(files) > MAX_FILES_PER_REQUEST:
            return jsonify({"error": f"Too many files -- max {MAX_FILES_PER_REQUEST} per request."}), 400

        jd_input = request.form.get("jd", "").strip()
        if not jd_input:
            return jsonify({"error": "No job description selected."}), 400

        try:
            jd = jd_loader.load(jd_input)
        except Exception:  # noqa: BLE001
            logger.exception("JD loading failed in /api/run")
            return jsonify({"error": "Could not load this job description. Check the server log for detail."}), 400

        # Security: never trust the client filename directly; save under a
        # generated per-request temp dir, reject non-.pdf uploads outright.
        job_id = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix=f"parseloom_{job_id}_") as tmp_dir:
            resumes = []
            for f in files:
                if not f.filename.lower().endswith(ALLOWED_EXTENSION):
                    continue  # silently skip non-PDFs, matches main.py's glob("*.pdf") behavior
                safe_name = secure_filename(f.filename) or f"{uuid.uuid4().hex}.pdf"
                saved_path = os.path.join(tmp_dir, safe_name)
                f.save(saved_path)
                resumes.append(parse_one_resume(saved_path))

            if not resumes:
                return jsonify({"error": "No valid .pdf files in the upload."}), 400

            results = [score_candidate(r, jd) for r in resumes]
            shortlist_data = build_shortlist(results, jd)

        return jsonify({"jd": jd.role, "result": shortlist_data})

    except Exception:  # noqa: BLE001
        # Security/robustness fix: without this, an unexpected bug
        # anywhere in the parse/score chain would crash the whole
        # request as an unhandled 500 -- with debug=True that means a
        # full interactive traceback rendered in the judge's browser
        # mid-demo. One bad resume should degrade gracefully, not take
        # the whole batch down.
        logger.exception("Unexpected error in /api/run")
        return jsonify({"error": "Something went wrong processing this batch. Check the server log for detail."}), 500


@app.route("/results")
def results_page():
    return render_template("results.html")


if __name__ == "__main__":
    # Security fix: debug=True enables Werkzeug's interactive debugger,
    # which renders full stack tracebacks (and, if ever reached, a
    # PIN-protected but still real remote-code-execution console) in the
    # browser on any unhandled error. Fine for isolated local dev, risky
    # on a hackathon venue's shared network. debug=False here;
    # TEMPLATES_AUTO_RELOAD above keeps template edits picking up live
    # without needing debug mode for it.
    app.run(debug=False, port=5000)
