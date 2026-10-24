"""Tests de la barrera del RECIBO REEJECUTABLE sin resolucion (WOT-2026-054d).

MUTATION en las dos direcciones que exige el DoD:

  placeholder sin "resuelto"   -> ROJO   test_placeholder_without_resolution_is_rejected
  placeholder CON "resuelto"   -> VERDE  test_placeholder_with_resolution_is_accepted

mas el caso real medido (dos sesiones, mismo comando con placeholder,
resultados opuestos, ninguna se equivocaba) reproducido como fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_escalation_receipt_resolution as cerr  # noqa: E402


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


_RECIBO_SIN_RESOLVER = """## RECIBO REEJECUTABLE

    command:  grep -c 'CTL-2026-014j' <DESTINO_ROOT>/.agent/collaboration/backlog.md
    exit_code: 1

## 5. PROCEDENCIA POR CLAIM
"""

_RECIBO_RESUELTO = """## RECIBO REEJECUTABLE

    command:  grep -c 'CTL-2026-014j' <DESTINO_ROOT>/.agent/collaboration/backlog.md
    exit_code: 1

Resuelto: <DESTINO_ROOT> = C:\\Users\\fdl\\Proyectos_Python\\Crear_Texto_LLM

## 5. PROCEDENCIA POR CLAIM
"""

_RECIBO_SIN_PLACEHOLDER = """## RECIBO REEJECUTABLE

    command:  grep -c 'CTL-2026-014j' C:\\Users\\fdl\\Proyectos_Python\\Crear_Texto_LLM\\backlog.md
    exit_code: 1

## 5. PROCEDENCIA POR CLAIM
"""

#: Revisor (modo 3): forma REAL de una ficha ya drenada
#: (`FP-20260829-escalado-crear-texto-llm-scope-vocabulary.tickets.md`), que
#: nombra la seccion como linea plana "RECIBO REEJECUTABLE (del emisor):"
#: SIN marcador `#` de heading -- el guard original (antes del fix) la
#: trataba como "seccion ausente" y pasaba en OK pese al placeholder sin
#: resolver.
_RECIBO_SIN_HEADING_MARKER = """Texto previo de la ficha.

RECIBO REEJECUTABLE (del emisor):
```
backlog_reconcile.py --motor-root <motor> --project-root <destino_CTL>
rc=0
```

## LO QUE NO ES EL DEFECTO
"""


def test_placeholder_without_resolution_is_rejected():
    section = cerr.extract_receipt_section(_RECIBO_SIN_RESOLVER)
    assert section is not None
    assert cerr.receipt_resolution_is_declared(section) is False


def test_placeholder_with_resolution_is_accepted():
    section = cerr.extract_receipt_section(_RECIBO_RESUELTO)
    assert section is not None
    assert cerr.receipt_resolution_is_declared(section) is True


def test_mutation_both_directions():
    """DoD (c): quitar 'Resuelto:' -> ROJO; devolverlo -> VERDE."""
    resolved_section = cerr.extract_receipt_section(_RECIBO_RESUELTO)
    assert cerr.receipt_resolution_is_declared(resolved_section) is True

    mutated = _RECIBO_RESUELTO.replace(
        "Resuelto: <DESTINO_ROOT> = C:\\Users\\fdl\\Proyectos_Python\\Crear_Texto_LLM\n\n",
        "",
    )
    mutated_section = cerr.extract_receipt_section(mutated)
    assert cerr.receipt_resolution_is_declared(mutated_section) is False


def test_no_placeholder_passes_trivially():
    section = cerr.extract_receipt_section(_RECIBO_SIN_PLACEHOLDER)
    assert section is not None
    assert cerr.receipt_resolution_is_declared(section) is True


def test_section_absent_is_out_of_scope():
    assert cerr.extract_receipt_section("# Ficha sin esa seccion\n\nTexto.\n") is None


def test_non_heading_section_label_is_still_detected(tmp_path):
    """Revisor (modo 3): la ficha REAL `FP-20260829-...-scope-vocabulary`
    nombra la seccion sin `#` ("RECIBO REEJECUTABLE (del emisor):"); antes
    del fix esto se trataba como seccion AUSENTE y pasaba OK pese al
    placeholder sin resolver."""
    section = cerr.extract_receipt_section(_RECIBO_SIN_HEADING_MARKER)
    assert section is not None
    assert cerr.receipt_resolution_is_declared(section) is False

    path = _write(
        tmp_path,
        "FP-20991231-escalado-prueba.tickets.md",
        _RECIBO_SIN_HEADING_MARKER,
    )
    level, message = cerr.check_file(path)
    assert level == "ERROR"
    assert "<motor>" in message or "<destino_CTL>" in message


def test_check_file_real_case_2026_08_06_divergent_sessions(tmp_path):
    """Reproduce el caso MEDIDO 2026-08-10: <DESTINO_ROOT> sin resolucion."""
    path = _write(
        tmp_path,
        "FP-20991231-escalado-prueba.tickets.md",
        f"# Ficha\n\n{_RECIBO_SIN_RESOLVER}",
    )

    level, message = cerr.check_file(path)

    assert level == "ERROR"
    assert "<DESTINO_ROOT>" in message


def test_check_file_grandfathered_ficha_warns_not_errors(tmp_path):
    path = _write(
        tmp_path,
        "FP-20260806-escalado-prueba.tickets.md",
        f"# Ficha\n\n{_RECIBO_SIN_RESOLVER}",
    )

    level, _ = cerr.check_file(path)

    assert level == "WARN"


def test_check_file_resolved_passes(tmp_path):
    path = _write(
        tmp_path,
        "FP-20991231-escalado-prueba.tickets.md",
        f"# Ficha\n\n{_RECIBO_RESUELTO}",
    )

    level, _ = cerr.check_file(path)

    assert level == "OK"


def test_main_cli_empty_inbox_returns_distinguishable_skip(tmp_path):
    inbox = tmp_path / "backlog_inbox"
    inbox.mkdir()

    rc = cerr.main(["--inbox", str(inbox)])

    assert rc == cerr.EXIT_EMPTY_UNIVERSE


def test_main_cli_exits_1_on_unresolved_placeholder(tmp_path, capsys):
    inbox = tmp_path / "backlog_inbox"
    inbox.mkdir()
    _write(
        inbox,
        "FP-20991231-escalado-prueba.tickets.md",
        f"# Ficha\n\n{_RECIBO_SIN_RESOLVER}",
    )

    rc = cerr.main(["--inbox", str(inbox)])

    assert rc == 1
    assert "<DESTINO_ROOT>" in capsys.readouterr().out
