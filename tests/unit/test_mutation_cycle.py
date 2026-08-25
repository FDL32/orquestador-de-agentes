"""WOT-2026-040d: el ciclo de mutation restaura SIEMPRE el working tree pre-mutacion.

El flujo historico ``aplicar mutante -> test cae -> revertir`` revertia con
``git checkout <fichero>``, que restaura a HEAD: si el FIX del ticket aun no
esta commiteado, ese checkout lo borra entero y el test sigue cayendo por la
razon equivocada (medido 2026-07-23, dos veces en el vuelo FP-20260723b). Este
test prueba que `run_cycle` restaura la copia PRE-mutacion (fix intacto) incluso
cuando la parada del ciclo pisa el fichero, y que ademas propaga el rc real del
comando.

Cobertura del DoD del ticket:
  (a) snapshot+restore del working tree antes/despues de la mutacion.
  (c) MUTACION: un ciclo cuyo comando SOBREESCRIBE el fichero -> al terminar, el
      fichero vuelve a su contenido pre-mutacion (el fix SIN commitear sobrevive).
      Si `run_cycle` no restaurase en `finally`, la primera asercion cae.
  (d) CONTROL NEGATIVO: el rc del comando se propaga tal cual, no enmascarado.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from mutation_cycle import main, restore, run_cycle, snapshot  # noqa: E402


def test_fix_survives_destructive_revert(tmp_path):
    """(c) El fix SIN commitear sobrevive a un ciclo que pisa el fichero.

    Reproduce FP-20260723b: el fichero lleva un fix aun sin commitear; la parada
    del ciclo "revierta" pisando el fichero con basura (como hacia `git checkout
    <fichero>`); al terminar, el working tree debe tener SU contenido
    pre-mutacion, no HEAD ni la basura.
    """
    target = tmp_path / "fixme.py"
    fix_content = b"def arreglada():\n    return 42  # fix sin commitear\n"
    target.write_bytes(fix_content)
    snap = snapshot([target])

    # La parada del ciclo es un comando que pisa el fichero y sale distinto de 0
    # (simula 'el test cae'). run_cycle debe restaurar el fix en su finally.
    code = f"import pathlib,sys; pathlib.Path(r'{target!s}').write_bytes(b'basura\\n'); sys.exit(4)"
    rc = run_cycle(snap, [sys.executable, "-c", code])

    assert rc == 4, f"propaga el rc real de la parada: {rc}"
    assert target.read_bytes() == fix_content, (
        "el fix sin commitear debe sobrevivir: el ciclo restaura el working tree "
        "pre-mutacion, no HEAD"
    )


def test_run_cycle_restores_even_when_no_file_was_mutated(tmp_path):
    """(c-bis) Restaurar es idempotente: aunque la parada no toque el fichero,
    el estado pre-mutacion queda intacto y el rc real se propaga."""
    target = tmp_path / "f.txt"
    original = b"estado pre-mutacion\n"
    target.write_bytes(original)
    snap = snapshot([target])
    code = "import sys; sys.exit(7)"
    rc = run_cycle(snap, [sys.executable, "-c", code])
    assert rc == 7
    assert target.read_bytes() == original


def test_snapshot_restore_roundtrip_preserves_exact_bytes(tmp_path):
    """Round-trip binario: bytes exactos, incluyendo CRLF y bytes no-ASCII."""
    blob = b"linea1\r\nlinea2\nlinea3\x00\xff"
    target = tmp_path / "bin.dat"
    target.write_bytes(blob)

    snap = snapshot([target])
    target.write_bytes(b"mutado")
    restore(snap)

    assert target.read_bytes() == blob


def test_cli_leading_double_dash_and_restore(tmp_path):
    """El CLI descarta el `--` de fin-de-opciones y restaura el working tree."""
    target = tmp_path / "f.txt"
    original = b"cli pre-mutacion\n"
    target.write_bytes(original)

    code = f"import pathlib,sys; pathlib.Path(r'{target!s}').write_bytes(b'piso\\n'); sys.exit(6)"
    rc = main(["--", str(target), "--", sys.executable, "-c", code])

    assert rc == 6, f"propaga el rc real: {rc}"
    assert target.read_bytes() == original
