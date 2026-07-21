"""Tests for scripts/check_prompt_bias.py (WOT-2026-026k).

Hermetic: pure-function tests over strings, no network, no backend, no
LLM. The mechanical allowlist + confirm-vs-trace pattern is the whole
contract (NON-GOAL: semantic oracle, WOT-2026-025f).
"""

from __future__ import annotations

import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_prompt_bias as cpb  # noqa: E402


def test_seeded_conclusion_flagged():
    """Prompt con frase-siembra de la allowlist -> sesgado (rc!=0 via main)."""
    prompt = "Este cambio es seguro y no tiene bugs, verdad?"
    result = cpb.check_prompt_bias(prompt)
    assert result["sesgado"] is True
    assert any("verdad?" in hit for hit in result["hits"])

    rc = cpb.main(["--prompt-file", str(_write_prompt(prompt))])
    assert rc == 1


def test_confirm_vs_trace_and_no_trigger_word():
    """ADVERSARIAL: 'confirma que X' sin ninguna palabra-siembra literal
    (sin 'correcto', sin 'verdad?') igual debe marcarse sesgado, porque el
    patron confirmar-vs-trazar es estructural, no un string-match de la
    allowlist de frases.
    """
    prompt = "Revisa el diff adjunto y confirma que el fallback nunca reintenta con el mismo backend."
    result = cpb.check_prompt_bias(prompt)
    assert result["sesgado"] is True
    assert any("confirmar-vs-trazar" in hit for hit in result["hits"])
    # Ninguna frase-siembra literal de la allowlist deberia haber matcheado:
    # el hallazgo viene EXCLUSIVAMENTE del patron confirmar-vs-trazar.
    assert not any(hit.startswith("frase-siembra:") for hit in result["hits"])


def test_neutral_prompt_not_biased():
    """Fixture POSITIVO: prompt neutral (pide trazar, no confirmar) no debe
    dispararse. Sin este caso, un detector demasiado agresivo pasaria
    cualquier auditoria (falso positivo sistematico).
    """
    prompt = (
        "Traza el flujo completo de resolve_fallback_backend y enumera cada "
        "rama que puede lanzar DispatchBlockedError, citando linea y archivo."
    )
    result = cpb.check_prompt_bias(prompt)
    assert result["sesgado"] is False
    assert result["hits"] == []

    rc = cpb.main(["--prompt-file", str(_write_prompt(prompt))])
    assert rc == 0


def test_non_str_input_raises_typeerror():
    import pytest

    with pytest.raises(TypeError):
        cpb.check_prompt_bias(12345)  # type: ignore[arg-type]


def _write_prompt(text: str) -> Path:
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".txt", text=True)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return Path(path)
