"""
Tests for src/extraction/pii_redact.py -- the data-minimization layer
(PROJECT_CONTEXT.md Section 10.5 / DESIGN_DECISIONS.md): email and phone
number must be extracted locally and redacted out of the text BEFORE it
ever reaches an external LLM API. No test file existed for this module
before this security audit pass -- added here specifically because "no
private data leaves the machine unnecessarily" is a security property that
was previously only exercised manually (per PROJECT_CONTEXT.md Section
11.7), never covered by an automated regression test.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extraction.pii_redact import extract_contact_and_redact


def test_single_email_and_phone_extracted_and_redacted():
    text = "Contact me at jane.doe@example.com or 9876543210 for more info."
    email, phone, redacted = extract_contact_and_redact(text)
    assert email == "jane.doe@example.com"
    assert phone == "9876543210"
    assert "jane.doe@example.com" not in redacted
    assert "9876543210" not in redacted
    assert "[EMAIL_REDACTED]" in redacted
    assert "[PHONE_REDACTED]" in redacted


def test_every_occurrence_is_redacted_not_just_the_first():
    # Regression for the real bug documented in PROJECT_CONTEXT.md Section
    # 11.7: an earlier version only redacted the FIRST email/phone match,
    # leaking a second one (e.g. a reference's contact info) straight
    # through to the LLM call.
    text = (
        "Personal: jane.doe@example.com, 9876543210. "
        "Reference: john.smith@college.edu, 8765432109."
    )
    email, phone, redacted = extract_contact_and_redact(text)
    # The single returned email/phone are still just the first match
    # (matches ParsedResume's single-value schema)...
    assert email == "jane.doe@example.com"
    assert phone == "9876543210"
    # ...but EVERY occurrence must be gone from what gets sent externally.
    assert "jane.doe@example.com" not in redacted
    assert "john.smith@college.edu" not in redacted
    assert "9876543210" not in redacted
    assert "8765432109" not in redacted


def test_no_contact_info_present_returns_none_and_unmodified_text():
    text = "Skilled in Python and React. No contact info listed here."
    email, phone, redacted = extract_contact_and_redact(text)
    assert email is None
    assert phone is None
    assert redacted == text


def test_empty_text_handled_gracefully():
    email, phone, redacted = extract_contact_and_redact("")
    assert email is None
    assert phone is None
    assert redacted == ""


def test_redacted_text_not_original_is_what_reaches_the_llm_call():
    """
    Integration-level check, not just a pii_redact.py unit test: confirms
    the actual text handed to call_llm_with_failover (and therefore sent
    over the network to a third-party provider) is the redacted version,
    never the raw text containing real contact info. Mocks the network
    call itself (no need to spend quota for this -- it's a data-flow
    check, not an accuracy check) and inspects exactly what was passed in.
    """
    from src.extraction.llm_extract import extract_structured_fields

    raw_resume_text = "Jane Doe. Email: jane.doe@example.com. Phone: 9876543210. Skills: Python."
    _, _, redacted_text = extract_contact_and_redact(raw_resume_text)

    captured_user_arg = {}

    def _fake_call_llm_with_failover(system, user, json_mode=True, **kwargs):
        captured_user_arg["user"] = user
        return '{"full_name": "Jane Doe", "skills": ["Python"]}'

    with patch("src.extraction.llm_extract.call_llm_with_failover", side_effect=_fake_call_llm_with_failover):
        extract_structured_fields(redacted_text)

    sent_text = captured_user_arg["user"]
    assert "jane.doe@example.com" not in sent_text
    assert "9876543210" not in sent_text
    assert "[EMAIL_REDACTED]" in sent_text
    assert "[PHONE_REDACTED]" in sent_text
