"""Redaction module for secrets and PII.

Protects logs, persistence, and events from accidental leakage of API keys,
tokens, JWTs, and Windows usernames.
"""

from __future__ import annotations

import re
from typing import Any


# Top-5 regex patterns for targeted high-fidelity redaction
PATTERNS = {
    # JWT Tokens (starts with eyJ, contains 3 base64 parts)
    "jwt": re.compile(r"\beyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*\b"),
    # Bearer or Basic authentication headers
    "auth_header": re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9-._~+/]+=*"),
    # API keys (typically starts with sk- and is followed by alphanumeric/dashes)
    "api_key": re.compile(r"\bsk-[a-zA-Z0-9-_]{20,}\b"),
    # Emails
    "email": re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),
}

# Windows Users Path username extractor (preserves directory structure for debugging)
USER_PATH_PATTERN = re.compile(
    r"(?i)([a-z]:[/\\]users[/\\])([a-zA-Z0-9_-]+)(?=[/\\]|$)"
)


def redact(text: str) -> str:
    """Redact secrets and PII from a raw text string.

    Uses static replacements and structural back-references to ensure
    idempotency: redact(redact(x)) == redact(x).
    """
    if not isinstance(text, str):
        return text

    # Apply general patterns
    for pattern in PATTERNS.values():
        text = pattern.sub("***REDACTED***", text)

    # Redact only the username in Windows paths to keep directory context
    text = USER_PATH_PATTERN.sub(r"\1***REDACTED***", text)

    return text


def redact_payload(data: Any) -> Any:
    """Recursively crawl dictionaries and lists to redact all string values."""
    if isinstance(data, dict):
        return {k: redact_payload(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_payload(v) for v in data]
    elif isinstance(data, str):
        return redact(data)
    else:
        return data
