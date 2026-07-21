"""
Security regression tests: real API key values must never appear in any
LLMError message -- including through the NEW Milestone 2 failover path
(Groq + Gemini both failing), which didn't exist when the original
key-scrubbing fix (PROJECT_CONTEXT.md Section 11.7) was written and tested.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_client import LLMError, _scrub_secrets, call_llm_with_failover


def test_scrub_secrets_redacts_a_configured_key_value():
    old = os.environ.get("GROQ_API_KEY")
    try:
        os.environ["GROQ_API_KEY"] = "sk-test-secret-value-abc123"
        scrubbed = _scrub_secrets("some error containing sk-test-secret-value-abc123 in the middle")
        assert "sk-test-secret-value-abc123" not in scrubbed
        assert "[REDACTED_GROQ_API_KEY]" in scrubbed
    finally:
        if old is not None:
            os.environ["GROQ_API_KEY"] = old
        else:
            os.environ.pop("GROQ_API_KEY", None)


def test_failover_error_message_never_contains_either_real_key():
    """
    Both Groq and Gemini fail (simulated connection error, which would
    normally embed the failed request URL -- and therefore any query-param
    key -- in the exception text). The combined error message
    call_llm_with_failover raises must contain neither real key value.
    """
    old_groq = os.environ.get("GROQ_API_KEY")
    old_gemini = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GROQ_API_KEY"] = "sk-real-secret-groq-key-value-12345"
        os.environ["GEMINI_API_KEY"] = "gm-real-secret-gemini-key-value-67890"

        with patch(
            "src.ai_client.requests.post",
            side_effect=requests.exceptions.ConnectionError(
                "failed to connect to https://bad-host/?key=sk-real-secret-groq-key-value-12345"
            ),
        ):
            with patch("src.ai_client.time.sleep"):  # skip real backoff delay in this test
                try:
                    call_llm_with_failover(system="s", user="u", primary="groq", fallback="gemini")
                    raise AssertionError("expected LLMError to be raised")
                except LLMError as exc:
                    message = str(exc)

        assert "sk-real-secret-groq-key-value-12345" not in message
        assert "gm-real-secret-gemini-key-value-67890" not in message
        # And the message should still be useful -- naming both providers,
        # just not their keys.
        assert "groq" in message
        assert "gemini" in message
    finally:
        for var, old in (("GROQ_API_KEY", old_groq), ("GEMINI_API_KEY", old_gemini)):
            if old is not None:
                os.environ[var] = old
            else:
                os.environ.pop(var, None)
