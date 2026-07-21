#!/usr/bin/env python3
"""WOT-2026-024h / C4': ningun fichero que VIAJA a un destino puede llevar
contratos de planning REALES del motor.

Contexto (medido, no relatado): el motor embarcaba
``.agent/planning/ticket_contracts.md`` (49881 B) con 3 contratos WOT reales del
dogfooding (021k / 023r / 023s). Un ``--install`` sobre un destino limpio los
depositaba tal cual: probe 2026-07-21, 3 cabeceras ``## WOT-`` en el destino.
DEC-024H-001 (opcion c) retira el fichero del control de versiones del motor.

Este guard es la barrera de la RETIRADA: impide que el seed vuelva por la puerta
de atras (otro nombre, otro fichero de planning) SIN que nadie se entere.

Ambito deliberado -- **la SUPERFICIE DISTRIBUIBLE, no el seed**. C4' es explicito:
no se crea un gate "anti-WOT sobre el seed" (no hay seed que vigilar). Se vigila
lo que VIAJA. La leccion de WOT-2026-024x es exactamente esta: un guard cableado y
que muerde puede estar mirando donde el fallo NO ocurre. Aqui el fallo ocurre en el
destino, asi que se mide la superficie que llega al destino.

Que cuenta como distribuible: los paths de ``MANIFEST.workspace`` bajo
``.agent/planning/`` que el instalador copiaria, MIRADOS EN EL ARBOL DE TRABAJO.
Estar gitignored NO exime: el instalador copia del filesystem (probe en la ruta
productiva, 2026-07-21). El motor en dogfooding puede tener planning local, pero
NO con contratos WOT reales dentro de una ruta que el manifiesto distribuye.

Before: ``--motor-root`` apunta a un repo motor con ``MANIFEST.workspace``.
During: resuelve los paths de planning declarados distribuibles y busca en cada
        fichero (no solo ``*.md``) cabeceras de contrato real -- cualquier nivel
        markdown cuyo titulo empiece por ``<PREFIJO>-YYYY-NNN`` (ver
        ``REAL_CONTRACT_RE``). Solo lee.
After:  exit 0 si ninguna superficie distribuible lleva contratos reales; exit 1 con
        el listado (fichero + ids COMPLETOS) si alguna los lleva. No muta nada.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_WORKSPACE = "MANIFEST.workspace"

# Cabecera de un contrato REAL. Un placeholder/plantilla (``## T-XXXX-NNN``,
# ``## <TICKET_ID>``) no casa: lo que contamina un destino es un ticket con
# identidad REAL de algun repo.
#
# Deliberadamente NO se ata al nivel 2 (``##``) ni al prefijo WOT: cualquier
# cabecera markdown cuyo titulo EMPIECE por un ID real cuenta. Motivo (review
# adversarial): `# WOT-...` o `### WOT-...` son igual de contaminantes, y el
# motor declara prefijos por destino (`CTL-`, `EXF-`, ...), asi que fijar la
# lista a WOT/WP/WT dejaria pasar un contrato real de otro repo. El grupo es
# NO-CAPTURANTE para que ``findall`` devuelva el ID COMPLETO y no solo el
# prefijo (si no, el remedio dice "WOT" en vez de "WOT-2026-021k").
REAL_CONTRACT_RE = re.compile(r"^#{1,6}\s+([A-Z]{2,4}-\d{4}-\d+[a-z]?)\b", re.MULTILINE)

PLANNING_PREFIX = ".agent/planning/"

# El instalador copia TODO fichero allowlisted, no solo markdown: escanear solo
# `*.md` dejaria pasar un contrato real en .txt/.json/.yaml bajo la misma ruta.
# Se excluye lo binario evidente por ruido, no por seguridad.
_SKIP_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".ico", ".woff", ".woff2"}
)


def read_distributable_planning_entries(motor_root: Path) -> list[str]:
    """Entradas de MANIFEST.workspace que caen bajo .agent/planning/."""
    manifest = motor_root / MANIFEST_WORKSPACE
    if not manifest.exists():
        return []
    entries: list[str] = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(PLANNING_PREFIX):
            entries.append(line)
    return entries


def find_contaminated(motor_root: Path) -> dict[str, list[str]]:
    """Ficheros distribuibles que llevan contratos reales -> ids encontrados.

    Se mide el ARBOL DE TRABAJO, no el indice de git. Es deliberado y esta MEDIDO:
    el instalador copia con ``shutil.copy2`` desde el filesystem (``copy_tree`` ->
    ``_copy_allowlisted_dir``), NO con ``git archive``. Un fichero UNTRACKED que
    caiga bajo una entrada del manifiesto VIAJA IGUAL.

    Probe que lo demuestra (2026-07-21, ruta productiva): con
    ``.agent/planning/ticket_contracts.md`` presente en disco pero NO trackeado
    (gitignored), ``install_agent_system.py --install --dest <tmp>`` rc=0 deposito
    el fichero en el destino con su cabecera ``## WOT-2026-021k``.

    Una version previa de este guard filtraba por ``git ls-files`` y daba exit 0
    sobre ese MISMO estado: un FALSO VERDE que la review adversarial cazo (4 de 7
    revisores lo señalaron de forma independiente). Git-tracked era el ORACULO
    EQUIVOCADO: la pregunta no es "¿se publica en el repo?" sino "¿lo copia el
    instalador?". Es la leccion de WOT-2026-024x -- un guard que muerde pero mira
    donde el fallo NO ocurre.

    Consecuencia asumida: el motor en dogfooding NO puede tener un
    ticket_contracts.md con contratos reales en su arbol, ni siquiera gitignored,
    porque ese fichero contaminaria cualquier install lanzado desde ese arbol.
    """
    hits: dict[str, list[str]] = {}
    for entry in read_distributable_planning_entries(motor_root):
        target = motor_root / entry
        candidates: list[Path] = []
        if target.is_dir():
            candidates = [
                p
                for p in sorted(target.rglob("*"))
                if p.is_file() and p.suffix.lower() not in _SKIP_SUFFIXES
            ]
        elif target.is_file():
            candidates = [target]
        for path in candidates:
            try:
                body = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            found = REAL_CONTRACT_RE.findall(body)
            if found:
                rel = path.relative_to(motor_root).as_posix()
                hits[rel] = list(found)
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed: ninguna superficie distribuible de planning puede llevar "
            "contratos reales del motor (WOT-2026-024h / C4')."
        )
    )
    parser.add_argument(
        "--motor-root",
        default=str(MOTOR_ROOT),
        help="Raiz del repo motor (por defecto: el repo de este script).",
    )
    args = parser.parse_args(argv)
    motor_root = Path(args.motor_root).resolve()

    hits = find_contaminated(motor_root)
    if not hits:
        print(
            "[distributable-planning] OK: ninguna superficie distribuible lleva "
            "contratos reales de planning"
        )
        return 0

    print(
        "[distributable-planning] FAIL: superficie distribuible con contratos "
        "REALES del motor (viajarian a cada destino nuevo):"
    )
    for rel, ids in sorted(hits.items()):
        print(f"  - {rel}: {', '.join(sorted(set(ids)))}")
    print(
        "\nRemedio: el motor NO versiona sus contratos de planning (DEC-024H-001, "
        "opcion c). Migra el contenido al ticket_contracts.md del WORKSPACE "
        "(append NO destructivo, marca de origen, sin borrar nada) y RETIRA el "
        "fichero del arbol del motor:\n"
        "  git rm --cached <fichero>   # si estaba trackeado\n"
        "  rm <fichero>                # SIEMPRE: gitignorarlo NO basta\n"
        "OJO: el instalador copia del FILESYSTEM, no de git. Un fichero untracked "
        "bajo una ruta del MANIFEST.workspace VIAJA IGUAL al destino (medido).\n"
        "NO crees un seed neutro ni un placeholder: el CONTRACT_GAP "
        "(CG-WOT-2026-024h.md) probo que ninguna forma pasa "
        "validate_contract_formation."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
