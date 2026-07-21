"""
Tests for the baseline security headers added during the Milestone 3
security audit (app.py::_add_security_headers).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402


def test_security_headers_present_on_every_response():
    client = app_module.app.test_client()
    for path in ["/", "/candidate", "/api/jds"]:
        resp = client.get(path)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "same-origin"
