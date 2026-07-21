"""
Milestone 2 tests: Groq-primary / Gemini-failover behavior in
src/ai_client.py::call_llm_with_failover, and the fact that a single-
provider caller (only one key configured) still works unchanged.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_client import LLMError, call_llm_with_failover


def test_primary_success_never_touches_fallback():
    with patch("src.ai_client.call_llm") as mock_call:
        mock_call.return_value = '{"ok": true}'
        result = call_llm_with_failover(system="s", user="u", primary="groq", fallback="gemini")
    assert result == '{"ok": true}'
    # Only one call -- the primary succeeded, fallback must never fire.
    assert mock_call.call_count == 1
    assert mock_call.call_args.kwargs["provider"] == "groq"


def test_primary_failure_triggers_fallback_and_fallback_succeeds():
    calls = []

    def fake_call_llm(system, user, provider=None, model=None, json_mode=True):
        calls.append(provider)
        if provider == "groq":
            raise LLMError("HTTP 429: rate limited")
        return '{"ok": true, "from": "gemini"}'

    with patch("src.ai_client.call_llm", side_effect=fake_call_llm):
        result = call_llm_with_failover(system="s", user="u", primary="groq", fallback="gemini")

    assert result == '{"ok": true, "from": "gemini"}'
    assert calls == ["groq", "gemini"]  # confirms Gemini was actually invoked, not just returned by luck


def test_both_providers_failing_raises_llm_error_mentioning_both():
    def fake_call_llm(system, user, provider=None, model=None, json_mode=True):
        raise LLMError(f"HTTP 500: {provider} is down")

    with patch("src.ai_client.call_llm", side_effect=fake_call_llm):
        with pytest.raises(LLMError) as exc_info:
            call_llm_with_failover(system="s", user="u", primary="groq", fallback="gemini")

    message = str(exc_info.value)
    assert "groq" in message
    assert "gemini" in message


def test_no_fallback_configured_propagates_primary_error_unchanged():
    # Single-provider behavior (e.g. a test/dev setup with only one key)
    # must keep working exactly as before -- no forced dependency on a
    # second provider being configured.
    with patch("src.ai_client.call_llm", side_effect=LLMError("HTTP 401: bad key")):
        with pytest.raises(LLMError, match="HTTP 401"):
            call_llm_with_failover(system="s", user="u", primary="groq", fallback="groq")
