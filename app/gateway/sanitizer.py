"""Input sanitisation: first line of defence against prompt injection & PII leak.

This does **not** try to be a complete security solution (that lives across
several layers), but it neutralises the most common attacks before user text
ever reaches the model context:

* strips control characters and hard length-caps input;
* redacts obvious PII (emails, phone numbers, long digit runs like cards);
* flags known override phrases ("ignore previous instructions", "system prompt")
  so downstream layers can wrap the text in delimiters and lower its trust.

Crucially, user text is never string-interpolated into the system prompt: the
LLM layer wraps it in explicit ``<user_input>`` delimiters (see app.llm).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MAX_LEN = 8_000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,15}(?!\d)")
_LONG_DIGITS = re.compile(r"\b\d{12,19}\b")  # card-like sequences

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(the\s+)?(above|previous)",
        r"system\s+prompt",
        r"reveal\s+your\s+(instructions|prompt)",
        r"игнорируй\s+(все\s+)?предыдущие\s+инструкции",
        r"системн\w*\s+промпт",
    )
]


@dataclass(slots=True, frozen=True)
class SanitizationResult:
    """Outcome of sanitising a single text field."""

    text: str
    injection_suspected: bool
    pii_redacted: bool


def sanitize_text(value: str) -> SanitizationResult:
    """Return a cleaned, length-bounded copy of ``value`` plus safety flags."""
    if not value:
        return SanitizationResult(text="", injection_suspected=False, pii_redacted=False)

    cleaned = _CONTROL_CHARS.sub("", value).strip()
    if len(cleaned) > _MAX_LEN:
        cleaned = cleaned[:_MAX_LEN]

    injection = any(p.search(cleaned) for p in _INJECTION_PATTERNS)

    redacted = cleaned
    redacted = _EMAIL.sub("[email]", redacted)
    redacted = _LONG_DIGITS.sub("[redacted-number]", redacted)
    redacted = _PHONE.sub("[phone]", redacted)
    pii = redacted != cleaned

    return SanitizationResult(text=redacted, injection_suspected=injection, pii_redacted=pii)
