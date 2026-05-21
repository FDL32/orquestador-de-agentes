from __future__ import annotations

import pytest

from bus.redact import redact, redact_payload


def test_redact_api_key():
    text = "Here is my key: sk-abcdefghijklmnopqrstuvwxyz12345"
    assert redact(text) == "Here is my key: ***REDACTED***"


def test_redact_jwt():
    text = "User token is eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    assert redact(text) == "User token is ***REDACTED***"


def test_redact_bearer_token():
    text = "Authorization: Bearer 12345-abcde.token_value"
    assert redact(text) == "Authorization: ***REDACTED***"

    text_lower = "authorization: bearer abcdef"
    assert redact(text_lower) == "authorization: ***REDACTED***"


def test_redact_email():
    text = "Contact us at support@example.com for help"
    assert redact(text) == "Contact us at ***REDACTED*** for help"


def test_redact_windows_user_path():
    text = r"Project located at C:\Users\fdl\Proyectos_Python\z_scripts"
    assert redact(text) == r"Project located at C:\Users\***REDACTED***\Proyectos_Python\z_scripts"

    # Forward slash variant
    text_slash = "Path: c:/users/fdl/some_dir"
    assert redact(text_slash) == "Path: c:/users/***REDACTED***/some_dir"


def test_redact_idempotency():
    raw_texts = [
        "Here is my key: sk-abcdefghijklmnopqrstuvwxyz12345",
        "User token is eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "Authorization: Bearer 12345-abcde.token_value",
        "Contact us at support@example.com for help",
        r"Project located at C:\Users\fdl\Proyectos_Python\z_scripts",
        "Multiple things: sk-abcdefghijklmnopqrstuvwxyz12345 and support@example.com",
    ]
    for text in raw_texts:
        once = redact(text)
        twice = redact(once)
        assert once == twice, f"Failed idempotency on: {text!r}"


def test_redact_payload_recursive():
    payload = {
        "user_email": "support@example.com",
        "nested": {
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz12345",
            "values": [
                "Bearer some-token",
                42,
                None,
            ],
        },
    }
    expected = {
        "user_email": "***REDACTED***",
        "nested": {
            "api_key": "***REDACTED***",
            "values": [
                "***REDACTED***",
                42,
                None,
            ],
        },
    }
    assert redact_payload(payload) == expected
