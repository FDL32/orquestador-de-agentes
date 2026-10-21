"""Tests for scripts/check_builder_dispatch_prompt.py.

Que protege
-----------
Que un prompt de arranque despachado a Kilo (Builder real o lente canal
`agent`) instruya expresamente leer `AGENTS.md`, porque Kilo no autocarga
nada (WOT-2026-108b). Sin esta comprobacion, la clausula de
`builder_invocation_contract.md` Seccion 1 depende solo de que quien
redacta el prompt se acuerde -- una NORMA, no una barrera.

Before / During / After
-----------------------
Before: no requiere estado externo; los fixtures son literales en el test.
During: llama a las funciones puras sobre texto en memoria. Sin red, sin I/O.
After: exit 0 sii el prompt declara la instruccion natal; WARN (no bloqueo)
    si menciona memoria del proyecto sin instruir leer sus punteros de capa 2.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_builder_dispatch_prompt import (
    has_agents_md_instruction,
    has_layer2_pointer_instruction,
    mentions_memory_topic,
)


PROMPT_SIN_INSTRUCCION = """# PROMPT DE ARRANQUE
Eres un Builder. Implementa el fix descrito en el ticket WOT-2026-999a.
Escribe tu resultado en .agent/planning/resultado.md.
"""

PROMPT_CON_INSTRUCCION = """# PROMPT DE ARRANQUE
Lee AGENTS.md entero antes de actuar.

Eres un Builder. Implementa el fix descrito en el ticket WOT-2026-999a.
"""

PROMPT_MEMORIA_SIN_PUNTERO = """# PROMPT DE ARRANQUE
Lee AGENTS.md entero antes de actuar.

Eres un Builder. Consolida la memoria del proyecto segun lo que encuentres.
"""

PROMPT_MEMORIA_CON_PUNTERO = """# PROMPT DE ARRANQUE
Lee AGENTS.md entero antes de actuar. La tarea toca memoria del proyecto:
lee tambien MEMORY.md y memory_rules.md antes de empezar.

Eres un Builder. Consolida la memoria del proyecto segun lo que encuentres.
"""


def test_prompt_without_instruction_fails() -> None:
    """El prompt que no pide leer AGENTS.md no cumple el invariante natal."""
    assert has_agents_md_instruction(PROMPT_SIN_INSTRUCCION) is False


def test_prompt_with_instruction_passes() -> None:
    """El prompt que pide leer AGENTS.md cumple el invariante natal."""
    assert has_agents_md_instruction(PROMPT_CON_INSTRUCCION) is True


# Frases que 4 lentes independientes (groq/qwen, mistral, gemini, cohere;
# DESIGN_REVIEW WOT-2026-108b, 2026-10-20) citaron como falsos negativos de
# la version por substring literal. Fijan el comportamiento corregido.
FALSE_NEGATIVE_PHRASES = (
    "Lee el archivo AGENTS.md completo antes de comenzar.",
    "Por favor, lee AGENTS.md antes de actuar.",
    "Lea AGENTS.md antes de actuar.",
    "Read the AGENTS.md file before starting.",
    "Consulta el archivo AGENTS.md para las convenciones del repo.",
    "Lee el AGENTS.md archivo.",
)


def test_natural_phrasings_no_longer_false_negative() -> None:
    """Las frases que las 4 lentes de la DESIGN_REVIEW citaron ya no bloquean."""
    for phrase in FALSE_NEGATIVE_PHRASES:
        assert has_agents_md_instruction(phrase) is True, phrase


def test_generic_engineering_memory_mention_is_not_a_false_positive() -> None:
    """'Memoria RAM'/'puntero nulo' no deben disparar la clausula de capa 2."""
    text = "Cuidado con una fuga de memoria y no desreferencies un puntero nulo."
    assert mentions_memory_topic(text) is False


def test_prompt_without_memory_topic_skips_layer2_check() -> None:
    """Un prompt que no toca memoria no activa la clausula condicional."""
    assert mentions_memory_topic(PROMPT_CON_INSTRUCCION) is False


def test_prompt_with_memory_topic_without_pointer_warns() -> None:
    """Un prompt que toca memoria sin instruir leer L2/L3 activa el WARN."""
    assert mentions_memory_topic(PROMPT_MEMORIA_SIN_PUNTERO) is True
    assert has_layer2_pointer_instruction(PROMPT_MEMORIA_SIN_PUNTERO) is False


def test_prompt_with_memory_topic_and_pointer_satisfies_clause() -> None:
    """Un prompt que toca memoria e instruye leer MEMORY.md cumple la clausula."""
    assert mentions_memory_topic(PROMPT_MEMORIA_CON_PUNTERO) is True
    assert has_layer2_pointer_instruction(PROMPT_MEMORIA_CON_PUNTERO) is True


def _run_cli(prompt_path: Path) -> subprocess.CompletedProcess[str]:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "check_builder_dispatch_prompt.py"
    )
    return subprocess.run(
        [sys.executable, str(script), str(prompt_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exits_nonzero_without_instruction(tmp_path: Path) -> None:
    """El CLI bloquea (exit 1) un prompt real sin la instruccion natal."""
    prompt_file = tmp_path / "prompt_sin_instruccion.md"
    prompt_file.write_text(PROMPT_SIN_INSTRUCCION, encoding="utf-8")
    result = _run_cli(prompt_file)
    assert result.returncode == 1
    assert "BLOQUEA" in result.stderr


def test_cli_exits_zero_with_instruction(tmp_path: Path) -> None:
    """El CLI pasa (exit 0) un prompt real con la instruccion natal."""
    prompt_file = tmp_path / "prompt_con_instruccion.md"
    prompt_file.write_text(PROMPT_CON_INSTRUCCION, encoding="utf-8")
    result = _run_cli(prompt_file)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_cli_exits_2_on_missing_file(tmp_path: Path) -> None:
    """El CLI falla con exit 2 si el fichero de prompt no existe."""
    result = _run_cli(tmp_path / "no_existe.md")
    assert result.returncode == 2
