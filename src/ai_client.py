"""
Provider-agnostic LLM call -- same pattern as the Next.js boilerplate
from the night before, ported to Python. Plain requests, no SDKs. One
function, three adapters. Switching providers is an env var change
(AI_PROVIDER), not a code change.
"""

import os
import time

import requests

DEFAULT_PROVIDER = os.environ.get("AI_PROVIDER", "gemini").lower()


class LLMError(Exception):
    pass


def call_llm(
    system: str,
    user: str,
    provider: str | None = None,
    model: str | None = None,
    json_mode: bool = True,
) -> str:
    provider = (provider or os.environ.get("AI_PROVIDER", DEFAULT_PROVIDER)).lower()

    if provider == "gemini":
        # gemini-2.5-flash free tier on this project is capped at 20
        # requests/DAY (confirmed by a real 429 mid-hackathon run, see
        # PROJECT_CONTEXT.md Section 11) -- nowhere near enough for a
        # 54-resume batch. gemini-flash-latest is a separate quota
        # bucket per Google's per-model quota system and was confirmed
        # working when 2.5-flash and 2.0-flash were both exhausted/blocked.
        return _call_gemini(system, user, model or "gemini-flash-latest", json_mode)
    if provider == "openai":
        return _call_openai(system, user, model or "gpt-4o-mini", json_mode)
    if provider == "anthropic":
        return _call_anthropic(system, user, model or "claude-3-5-sonnet-20241022")
    if provider == "groq":
        return _call_groq(system, user, model or "llama-3.3-70b-versatile", json_mode)
    raise LLMError(f"Unknown AI provider: {provider}")


def _call_gemini(system: str, user: str, model: str, json_mode: bool) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY is not set")

    # Key passed via header, NOT as a "?key=..." URL query param. A
    # real security issue was found and fixed here: requests-library
    # connection exceptions (timeouts, DNS failures) stringify to
    # include the full request URL -- confirmed by reproducing it
    # directly. With the key in the URL, a network-level failure would
    # leak the raw API key into the LLMError message, which
    # parse_one_resume writes straight into resume.parse_notes, which
    # write_parse_quality_report writes into parse_quality_report.md --
    # a file this repo's .gitignore explicitly keeps tracked as a
    # required submission deliverable. That would have committed a live
    # API key to a public hackathon repo. Google's Generative Language
    # API accepts the key via the x-goog-api-key header as an
    # alternative to the query param, which avoids this entirely.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    body = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        # maxOutputTokens set explicitly: newer Gemini models (e.g.
        # gemini-flash-latest / 3.5-flash) spend part of the output
        # budget on internal "thinking" tokens by default, which was
        # silently truncating the JSON response mid-array on a real
        # resume run (confirmed via a real "Could not parse LLM
        # response as JSON" failure). thinkingBudget: 0 disables that
        # for models that support it; harmless no-op on models that don't.
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    resp = _post_with_retry(url, body, headers=headers)
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected Gemini response shape: {data}") from exc


def _call_openai(system: str, user: str, model: str, json_mode: bool) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("OPENAI_API_KEY is not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    resp = _post_with_retry(url, body, headers=headers)
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected OpenAI response shape: {data}") from exc


def _call_groq(system: str, user: str, model: str, json_mode: bool) -> str:
    # Groq's API is OpenAI-compatible (same request/response shape), so
    # this is a straight adapter reuse of the _call_openai pattern
    # against a different base URL -- no new SDK, fits the existing
    # provider-agnostic design. Added as a free-tier fallback after the
    # Gemini free-tier key hit its 20-requests/day/model cap mid-run on
    # real data (see PROJECT_CONTEXT.md Section 11 / 12).
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set")

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    resp = _post_with_retry(url, body, headers=headers)
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected Groq response shape: {data}") from exc


def _call_anthropic(system: str, user: str, model: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set")

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "system": system,
        "max_tokens": 1500,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": user}],
    }

    resp = _post_with_retry(url, body, headers=headers)
    data = resp.json()
    try:
        return data["content"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected Anthropic response shape: {data}") from exc


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_SECRET_ENV_VARS = ["GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"]


def _scrub_secrets(text: str) -> str:
    """
    Defense in depth, on top of moving the Gemini key out of the URL:
    strip any of our own configured API key values out of a string
    before it's allowed into an LLMError message (which callers put
    into resume.parse_notes -> a real, tracked submission file). Cheap
    and can't make things worse -- if a key isn't set, .replace() on an
    empty string is a no-op.
    """
    for var in _SECRET_ENV_VARS:
        value = os.environ.get(var)
        if value:
            text = text.replace(value, f"[REDACTED_{var}]")
    return text


def _post_with_retry(url: str, body: dict, headers: dict | None = None, retries: int = 4):
    headers = headers or {"Content-Type": "application/json"}
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=30)
            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < retries:
                time.sleep(min(2 ** attempt, 15))  # exponential backoff, capped at 15s
                continue
            if not resp.ok:
                raise LLMError(_scrub_secrets(f"HTTP {resp.status_code}: {resp.text[:500]}"))
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 15))
                continue
    raise LLMError(_scrub_secrets(f"Request failed after {retries + 1} attempts: {last_exc}"))
