"""
Frontend JS checks for templates/index.html and templates/candidate.html.

This app has no browser automation (documented, not an oversight --
SESSION_HANDOFF.md and REBUILD_PLAN.md's Milestone 5 section both say so
explicitly). Real DOM/window behavior (tab close, focus return) genuinely
can't be verified by pytest and needs an actual browser click-through.

What CAN be verified without a browser, and is worth codifying as a real,
repeatable test instead of an ad-hoc one-off check:
  1. The <script> block in each template is at least syntactically valid
     JS (`node --check`) -- catches a typo/syntax error that would
     silently break the whole page with no server-side signal at all.
  2. Specific, previously-real bugs in this JS stay fixed. Codifying the
     exact code pattern that caused a bug (rather than just "the page
     loads") is what makes this a regression test, not a smoke test.

Bug this file guards against (found and fixed this session, Milestone 5
follow-up): reopening a historical run via the "Past Runs" list rendered
results but never wrote that payload to
localStorage['parseloom_last_run'] -- the only place candidate.html reads
from (it is deliberately stateless / makes no second network request).
Opening a candidate's detail page from a reopened past run therefore
showed stale data from an earlier live run this session, or "Candidate
not found" if none had happened yet. Fixed in templates/index.html's
past-run click handler by persisting the payload before rendering it,
mirroring what the live-run submit handler already does.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

NODE_AVAILABLE = shutil.which("node") is not None


def _extract_script(template_name: str) -> str:
    html = (TEMPLATES_DIR / template_name).read_text()
    match = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    assert match, f"No <script> block found in {template_name}"
    return match.group(1)


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in this environment")
@pytest.mark.parametrize("template_name", ["index.html", "candidate.html"])
def test_script_block_is_valid_js(template_name):
    script = _extract_script(template_name)
    # `node --check /dev/stdin` is unreliable across environments (fails
    # with ENOENT against a pipe fd in this sandbox specifically) -- a real
    # temp file is the portable way to hand node a syntax-checkable script,
    # works identically here and on a normal developer machine.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as tmp:
        tmp.write(script)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["node", "--check", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    assert result.returncode == 0, (
        f"{template_name}'s <script> block has a JS syntax error:\n{result.stderr}"
    )


def test_past_run_click_handler_persists_to_local_storage_before_rendering():
    """
    Regression guard for the bug described in the module docstring.

    Isolates the past-run click handler's body (between the
    `pastRunsListEl.addEventListener('click'` line and its matching
    closing `});`) and asserts that a write to
    localStorage['parseloom_last_run'] happens, and happens before
    renderResults(data) is called -- matching the live-run handler's own
    ordering (save first, then render), so candidate.html always has real
    data to read regardless of which path populated the results view.
    """
    script = _extract_script("index.html")

    start = script.index("pastRunsListEl.addEventListener('click'")
    # The handler body ends at the first "});" that closes this
    # addEventListener call -- scoped narrowly on purpose so this test
    # doesn't accidentally match localStorage/renderResults calls
    # elsewhere in the file (e.g. the live-run submit handler, which is
    # expected to have its own, separate, already-correct pair).
    end = script.index("});", start) + len("});")
    handler_body = script[start:end]

    set_item_idx = handler_body.find("localStorage.setItem('parseloom_last_run'")
    render_idx = handler_body.find("renderResults(data)")

    assert set_item_idx != -1, (
        "Past-run click handler no longer persists the reopened run to "
        "localStorage['parseloom_last_run'] -- candidate.html's 'View full "
        "details' links will show stale or missing data for historical runs."
    )
    assert render_idx != -1, "Past-run click handler no longer calls renderResults(data)."
    assert set_item_idx < render_idx, (
        "localStorage must be updated BEFORE renderResults() runs, matching the "
        "live-run handler's ordering -- otherwise a 'View full details' click "
        "fired quickly after render could still race against an unset/stale value."
    )


def test_live_run_submit_handler_also_persists_before_rendering():
    """
    Sanity check that the live-run path (which this session's fix was
    modeled on) still has the same save-before-render ordering it always
    had -- if this ever regresses too, the historical-run fix above would
    be modeled on a broken pattern.
    """
    script = _extract_script("index.html")

    start = script.index("form.addEventListener('submit'")
    end = script.index("});", script.rindex("finally {", start))
    handler_body = script[start:end]

    set_item_idx = handler_body.find("localStorage.setItem('parseloom_last_run'")
    render_idx = handler_body.find("renderResults(finalData)")

    assert set_item_idx != -1
    assert render_idx != -1
    assert set_item_idx < render_idx
