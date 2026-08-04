"""Guard: una nota operativa que PROHIBE una via por fallo debe llevar fecha.

WOT-2026-026t DoD-(c). El defecto que cierra, medido: un prompt ordenaba lanzar
el bucle "POR LA PRIMITIVA send_to_profile (NO por `ensemble_dispatch.py run`:
cuelga)". El hang se arreglo en WOT-2026-026n, pero la nota siguio en el prompt
y los ejecutores la acataron sin re-verificar -- coste medido: 16 ensembles con
0 filas de scorecard, porque la telemetria vivia en el runner que la nota
prohibia.

CLASE DEL DEFECTO: la REGLA CERO ("este prompt no es evidencia") se aplicaba a
SHAs y premisas del DAG, pero NO a las NOTAS OPERATIVAS -- que es justo donde
nadie mira, porque parecen instruccion y no premisa. Una nota asi es una PREMISA
DISFRAZADA DE ORDEN: afirma un hecho del mundo ("A falla") que caduca solo.

CONTRATO: si un texto normativo prohibe usar algo PORQUE FALLA, debe declarar
CUANDO se midio (fecha ISO) o COMO re-verificarlo (SHA / comando). Sin marca, la
nota caduca en silencio y nadie puede distinguir "sigue roto" de "se arreglo y
nadie actualizo el texto".

ALCANCE DELIBERADAMENTE ESTRECHO (leccion de WOT-2026-024u -> WOT-2026-025c:
tokenizar prosa para adivinar intencion NO CONVERGE; 5 parches, 5 agujeros).
Este guard NO interpreta prosa: exige la CO-OCURRENCIA de tres piezas literales
en una MISMA linea -- una negacion imperativa, un identificador de codigo entre
backticks, y un verbo de fallo. Una frase en prosa natural no las junta por
accidente. Si algun dia hay que relajarlo o ampliarlo con heuristicas, se abre
ficha: NO se parchea el patron.

Before: existe `prompts/` (y opcionalmente `skills/`) bajo la raiz del repo.
During: lee cada .md, evalua linea a linea; sin I/O de red ni escritura.
After: exit 0 si toda nota-prohibicion lleva marca de frescura; exit 1 listando
    fichero:linea y el texto ofensor. No lanza; los errores de lectura se
    reportan como violacion (fail-closed).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Superficies NORMATIVAS: texto que un ejecutor lee como instruccion vigente.
SCAN_DIRS = ("prompts", "skills")

# Pieza 1: negacion imperativa dirigida a usar/lanzar algo.
_PROHIBITION = re.compile(
    r"\bNO\s+(?:us(?:es|ar|e)|lances?|lanzar|invoques?|invocar|corras?|correr|ejecutes?|ejecutar)\b",
    re.IGNORECASE,
)

# Pieza 2: un identificador de CODIGO entre backticks (`x.py`, `cmd run`, ...).
# Exigirlo evita que prosa normativa generica ("no uses rutas absolutas") muerda:
# la nota que este guard persigue senala SIEMPRE un artefacto ejecutable concreto.
_CODE_REF = re.compile(r"`[^`]*[A-Za-z0-9_][^`]*`")

# Pieza 3: el MOTIVO es un fallo observado (lo que caduca), no una politica.
_FAILURE_VERB = re.compile(
    r"\b(cuelga|se\s+cuelga|falla|rompe|peta|no\s+funciona|esta\s+roto|timeout|se\s+bloquea)\b",
    re.IGNORECASE,
)

# Marca de frescura aceptada: fecha ISO, SHA corto, o una remision explicita a
# como re-verificarlo. Cualquiera de las tres basta.
_FRESHNESS = re.compile(
    r"(\b\d{4}-\d{2}-\d{2}\b"  # fecha ISO
    r"|\bcommit[:\s]+[0-9a-f]{7,40}\b"  # commit citado
    r"|\b[0-9a-f]{7,40}\b(?=\s|\)|,|\.)"  # SHA suelto
    r"|\bre-?verifica|\bre-?medi|\bprobe\b|\bverificado\b)",
    re.IGNORECASE,
)

# Ventana de contexto: la marca puede estar en la propia linea o en la siguiente
# (las notas suelen partirse por ancho de linea en los prompts).
_LOOKAHEAD = 2


def _is_prohibition_note(line: str) -> bool:
    """La linea es una nota que prohibe una via POR FALLO observado."""
    return bool(
        _PROHIBITION.search(line)
        and _CODE_REF.search(line)
        and _FAILURE_VERB.search(line)
    )


def _has_freshness(lines: list[str], idx: int) -> bool:
    """Hay marca de frescura en la linea o en las `_LOOKAHEAD` siguientes."""
    window = lines[idx : idx + 1 + _LOOKAHEAD]
    return any(_FRESHNESS.search(candidate) for candidate in window)


def scan_file(path: Path) -> list[str]:
    """Violaciones de un fichero. Un fichero ilegible ES una violacion."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: no se puede leer ({exc})"]

    violations = []
    for idx, line in enumerate(lines):
        if not _is_prohibition_note(line):
            continue
        if _has_freshness(lines, idx):
            continue
        try:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel = str(path)
        violations.append(f"{rel}:{idx + 1}: {line.strip()[:140]}")
    return violations


def collect_files(root: Path) -> list[Path]:
    """Todos los .md de las superficies normativas, orden estable."""
    files: list[Path] = []
    for name in SCAN_DIRS:
        directory = root / name
        if directory.is_dir():
            files.extend(sorted(directory.rglob("*.md")))
    return files


def main() -> int:
    """Exit 0 si no hay notas-prohibicion sin fechar; 1 en caso contrario."""
    files = collect_files(PROJECT_ROOT)
    violations: list[str] = []
    for path in files:
        violations.extend(scan_file(path))

    if violations:
        print(
            "[stale-operational-note] "
            f"{len(violations)} nota(s) que prohiben una via POR FALLO sin marca de frescura:"
        )
        for item in violations:
            print(f"  - {item}")
        print(
            "\nUna nota asi es una PREMISA disfrazada de orden: afirma que algo falla, "
            "y eso caduca.\nAnade la fecha de la medicion (2026-08-04), el commit que lo "
            "arreglo, o el probe que\nlo re-verifica. Contexto: WOT-2026-026t."
        )
        return 1

    print(
        f"[stale-operational-note] OK: {len(files)} fichero(s) normativos, "
        "ninguna nota-prohibicion sin fechar"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
