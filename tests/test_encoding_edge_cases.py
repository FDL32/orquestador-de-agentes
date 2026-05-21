"""Tests for safe_print encoding edge cases in completion_checker."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add .agent to path for imports
agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from completion_checker import safe_print  # noqa: E402


class TestSafePrintEncoding:
    def test_safe_print_ascii(self):
        """safe_print maneja texto ASCII normalmente."""
        with patch("builtins.print") as mock_print:
            safe_print("Hello World")
            mock_print.assert_called_once_with("Hello World", end="\n")

    def test_safe_print_unicode_supported(self):
        """safe_print maneja Unicode soportado por la consola."""
        with patch("builtins.print") as mock_print:
            safe_print("CafÃ© rÃ©sumÃ© naÃ¯ve")
            mock_print.assert_called_once_with("CafÃ© rÃ©sumÃ© naÃ¯ve", end="\n")

    def test_safe_print_encoding_error_fallback(self):
        """safe_print maneja errores de encoding de forma segura."""
        try:
            safe_print("CafÃ© rÃ©sumÃ© naÃ¯ve")
        except Exception as e:
            pytest.fail(f"safe_print raised unexpected exception: {e}")

    def test_safe_print_emojis_fallback(self):
        """safe_print maneja emojis y sÃ­mbolos especiales."""
        try:
            safe_print("âœ… Task completed ðŸŽ‰")
        except Exception as e:
            pytest.fail(f"safe_print raised unexpected exception: {e}")

    def test_safe_print_bom_handling(self):
        """safe_print maneja entrada con BOM o marcas de encoding."""
        bom_text = "\ufeffHello World"
        with patch("builtins.print") as mock_print:
            safe_print(bom_text)
            mock_print.assert_called_once_with(bom_text, end="\n")

    def test_safe_print_empty_string(self):
        """safe_print maneja string vacÃ­o."""
        with patch("builtins.print") as mock_print:
            safe_print("")
            mock_print.assert_called_once_with("", end="\n")

    def test_safe_print_custom_end(self):
        """safe_print respeta parÃ¡metro end."""
        with patch("builtins.print") as mock_print:
            safe_print("Test", end="")
            mock_print.assert_called_once_with("Test", end="")
