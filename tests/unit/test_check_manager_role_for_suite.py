"""Tests for the role-gate that protects `run_pytest_safe.py --level all`.

WOT-2026-117a: demuestra que la barrera BLOQUEA cuando TURN.md declara un rol
no-Manager y PERMITE cuando declara Manager o cuando TURN.md esta ausente
(caso motor CODE-ONLY / sesion de un solo Builder, ver docstring del modulo
bajo prueba para el limite declarado).
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_manager_role_for_suite import (
    SELFCHECK_EXEMPT_ENV,
    evaluate_role_gate,
    read_turn_role,
)


def _write_turn(tmp_path: Path, role: str) -> Path:
    turn_dir = tmp_path / ".agent" / "collaboration"
    turn_dir.mkdir(parents=True, exist_ok=True)
    turn_path = turn_dir / "TURN.md"
    turn_path.write_text(
        f"""# TURNO ACTUAL

## Agente Activo

| Campo | Valor |
|-------|-------|
| **ROL** | **{role}** |
| **Plan ID** | WOT-2026-117a |
""",
        encoding="utf-8",
    )
    return turn_path


def test_read_turn_role_parses_canonical_table_row(tmp_path: Path) -> None:
    turn_path = _write_turn(tmp_path, "BUILDER")
    assert read_turn_role(turn_path) == "BUILDER"


def test_read_turn_role_returns_none_when_file_absent(tmp_path: Path) -> None:
    assert read_turn_role(tmp_path / "nope" / "TURN.md") is None


def test_read_turn_role_returns_none_when_row_missing(tmp_path: Path) -> None:
    turn_dir = tmp_path / ".agent" / "collaboration"
    turn_dir.mkdir(parents=True)
    turn_path = turn_dir / "TURN.md"
    turn_path.write_text("# TURNO ACTUAL\n\nsin fila ROL\n", encoding="utf-8")
    assert read_turn_role(turn_path) is None


def test_gate_blocks_when_role_is_builder(tmp_path: Path) -> None:
    _write_turn(tmp_path, "BUILDER")
    allowed, reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is False
    assert "BUILDER" in reason
    assert "BLOQUEADO" in reason


def test_gate_blocks_when_role_is_revisor(tmp_path: Path) -> None:
    _write_turn(tmp_path, "REVISOR")
    allowed, reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is False
    assert "REVISOR" in reason


def test_gate_allows_when_role_is_manager(tmp_path: Path) -> None:
    _write_turn(tmp_path, "MANAGER")
    allowed, reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is True
    assert "Manager autorizado" in reason


def test_gate_allows_when_role_is_manager_lowercase(tmp_path: Path) -> None:
    _write_turn(tmp_path, "manager")
    allowed, _reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is True


def test_gate_allows_when_turn_file_absent(tmp_path: Path) -> None:
    allowed, reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is True
    assert "ausente" in reason


def test_gate_allows_when_turn_file_unparseable(tmp_path: Path) -> None:
    turn_dir = tmp_path / ".agent" / "collaboration"
    turn_dir.mkdir(parents=True)
    (turn_dir / "TURN.md").write_text("ruido sin tabla\n", encoding="utf-8")
    allowed, reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is True
    assert "no se bloquea" in reason


# WOT-2026-117a (fix post-revision adversarial): regresion confirmada por
# Codex -- la version original bloqueaba el self-check LEGITIMO del Builder
# (run_gates_dispatch.py, exento por AGENTS.md) porque "TURN.md ausente" no
# distingue "sin bus" de "ticket de un solo Builder con TURN.md=BUILDER
# vivo". La exencion explicita por invocador conocido corrige esto.


def test_selfcheck_exemption_bypasses_block_even_with_builder_role(
    tmp_path: Path,
) -> None:
    """La regresion confirmada: BUILDER + exencion -> PERMITE (antes: bloqueaba)."""
    _write_turn(tmp_path, "BUILDER")
    allowed, reason = evaluate_role_gate(tmp_path, env={SELFCHECK_EXEMPT_ENV: "1"})
    assert allowed is True
    assert "Exento" in reason


def test_selfcheck_exemption_bypasses_block_even_with_revisor_role(
    tmp_path: Path,
) -> None:
    _write_turn(tmp_path, "REVISOR")
    allowed, _reason = evaluate_role_gate(tmp_path, env={SELFCHECK_EXEMPT_ENV: "1"})
    assert allowed is True


def test_without_exemption_builder_role_still_blocks(tmp_path: Path) -> None:
    """Control negativo: sin la variable, el bloqueo original sigue vigente."""
    _write_turn(tmp_path, "BUILDER")
    allowed, _reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is False


def test_exemption_env_var_empty_string_does_not_exempt(tmp_path: Path) -> None:
    """Una cadena vacia no cuenta como presencia (evita el footgun `""`)."""
    _write_turn(tmp_path, "BUILDER")
    allowed, _reason = evaluate_role_gate(tmp_path, env={SELFCHECK_EXEMPT_ENV: ""})
    assert allowed is False


def test_read_turn_role_handles_invalid_utf8_without_raising(tmp_path: Path) -> None:
    """Hallazgo #4 de la revision: UnicodeDecodeError no estaba capturado."""
    turn_dir = tmp_path / ".agent" / "collaboration"
    turn_dir.mkdir(parents=True)
    turn_path = turn_dir / "TURN.md"
    turn_path.write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")
    assert read_turn_role(turn_path) is None


def test_gate_allows_when_turn_file_has_invalid_utf8(tmp_path: Path) -> None:
    turn_dir = tmp_path / ".agent" / "collaboration"
    turn_dir.mkdir(parents=True)
    (turn_dir / "TURN.md").write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")
    allowed, _reason = evaluate_role_gate(tmp_path, env={})
    assert allowed is True
