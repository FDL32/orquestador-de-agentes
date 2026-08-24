"""WOT-2026-058r: allowlist declarable por el DESTINO para deuda preexistente.

`check_encoding_guard` no podia dar `exit 0` sobre rutas del destino: su
`ALLOWLIST` esta vacia y `_allowlist_relative()` devuelve `None` para ficheros
fuera del motor, asi que cualquier corrupcion PREEXISTENTE del destino bloquea el
gate sin via de excepcion declarada.

Medido 2026-08-23 en el cierre de `Crear_Texto_LLM`: 3 ficheros con corrupcion
preexistente daban `rc=1`; verificado que eran preexistentes extrayendo los blobs
de `HEAD~1` a un directorio limpio (fingerprints identicos caracter por caracter).

La excepcion es POR FICHERO DECLARADO, nunca por patron: un fichero NUEVO con la
misma corrupcion debe seguir bloqueando. Esa asimetria es el punto del ticket --
tolerar deuda historica sin abrir la puerta a deuda nueva.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD = PROJECT_ROOT / "scripts" / "check_encoding_guard.py"

# Mojibake real: "configuración" mal decodificada (UTF-8 leido como cp1252).
_MOJIBAKE = "# Documento de configuraciÃ³n del proyecto\n"


def _run_guard(*paths: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD), *[str(p) for p in paths]],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def _destino(tmp_path: Path) -> Path:
    root = tmp_path / "repo_destino"
    (root / ".agent").mkdir(parents=True)
    return root


def test_058r_destino_corruption_blocks_without_allowlist(tmp_path: Path) -> None:
    """DoD (c): SIN allowlist declarada, el comportamiento actual se conserva.

    Es el control que impide que el fix se convierta en una puerta abierta.
    """
    root = _destino(tmp_path)
    bad = root / "PROMPT_PREEXISTENTE.md"
    bad.write_text(_MOJIBAKE, encoding="utf-8")

    result = _run_guard(bad)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "PROMPT_PREEXISTENTE.md" in (result.stdout + result.stderr)


def test_058r_declared_allowlist_entry_does_not_block(tmp_path: Path) -> None:
    """DoD (a)+(b): un fichero DECLARADO por el destino no bloquea, y el guard
    CITA la declaracion en su salida (una excepcion muda seria indistinguible de
    un guard que no miro)."""
    root = _destino(tmp_path)
    bad = root / "PROMPT_PREEXISTENTE.md"
    bad.write_text(_MOJIBAKE, encoding="utf-8")
    (root / ".agent" / "encoding_allowlist.json").write_text(
        json.dumps(
            {
                "owner": "WOT-2026-058r",
                "entries": ["PROMPT_PREEXISTENTE.md"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_guard(bad)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "WOT-2026-058r" in output, "el guard debe CITAR el ticket dueno"


def test_058r_new_file_with_same_corruption_still_blocks(tmp_path: Path) -> None:
    """DoD (b), la mitad que de verdad importa: la excepcion es POR FICHERO, no
    por patron. Un fichero NUEVO con la MISMA corrupcion sigue bloqueando.

    Sin esta asercion, el test anterior pasaria con una allowlist por glob -- que
    es exactamente la puerta abierta que este ticket NO quiere.
    """
    root = _destino(tmp_path)
    declared = root / "PROMPT_PREEXISTENTE.md"
    declared.write_text(_MOJIBAKE, encoding="utf-8")
    fresh = root / "PROMPT_NUEVO.md"
    fresh.write_text(_MOJIBAKE, encoding="utf-8")
    (root / ".agent" / "encoding_allowlist.json").write_text(
        json.dumps({"owner": "WOT-2026-058r", "entries": ["PROMPT_PREEXISTENTE.md"]})
        + "\n",
        encoding="utf-8",
    )

    result = _run_guard(declared, fresh)
    output = result.stdout + result.stderr

    assert result.returncode == 1, output
    # el NUEVO se reporta como ERROR de corrupcion...
    assert any(
        "PROMPT_NUEVO.md" in line and "Mojibake" in line for line in output.splitlines()
    ), output
    # ...y el DECLARADO no aparece como error (solo, si acaso, como eximido)
    assert not any(
        "PROMPT_PREEXISTENTE.md" in line and "Mojibake" in line
        for line in output.splitlines()
    ), output
