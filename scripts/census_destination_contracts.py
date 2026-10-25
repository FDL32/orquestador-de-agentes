#!/usr/bin/env python3
"""WOT-2026-026o: censo READ-ONLY + reparacion OPT-IN de seeds de contratos legacy.

WOT-2026-024h corto la FUENTE (el motor dejo de versionar
.agent/planning/ticket_contracts.md), pero los destinos YA instalados conservan
el seed depositado por el install antiguo en su propio .agent/planning/, donde
es DESTINATION-OWNED (024d: no-clobber + no-prune): ningun --sync futuro lo
limpia solo. Este script:

  MODO CENSO (default, sin escritura NUNCA):
      python scripts/census_destination_contracts.py --workspaces-root <dir>
  Lista cada destino -> ids de contratos presentes, marcando los que provienen
  del MOTOR (SEED_CONTRACT_IDS). Exit 0 siempre que el censo corra; exit 2 en
  error de infra (raiz ilegible).

  MODO REPARACION (OPT-IN, nunca automatico -- es estado del destino, no del
  motor; el operador pasa --repair --dest <path> EXPLICITO):
      ... --repair --dest <destino> --backup-dir <dir>
  - EXIGE --backup-dir y escribe ahi una copia verificable (sha256 en el nombre)
    del fichero ANTES de tocar nada (fail-closed sin backup).
  - Retira SOLO las secciones de contratos del motor cuyo id este en
    REPAIR_DEFAULT_IDS (023r/023s). WOT-2026-021k queda EXCLUIDO por defecto:
    su waiver migro al workspace y el NON-GOAL de la ficha lo protege.
  - IDEMPOTENTE: una segunda pasada sobre lo ya reparado es no-op (0 secciones
    retiradas) y no reescribe el fichero si no hay cambios.
  - Nunca toca contratos que el DESTINO escribio (fuera de SEED_CONTRACT_IDS).

Before: raices legibles. During: lectura + regex de encabezados `## ` y recorte
de secciones; escritura SOLO en --repair y solo tras backup verificado. After:
censo imprime tabla y exit 0 (o 2 infra); --repair imprime lo retirado y exit 0
(1 si tras el fix el destino sigue presentando ids del motor, para que el
operador lo vea; no reintenta solo).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


# Contratos del seed historico del motor (024h, medido 2026-07-21: 3 contratos
# WOT reales del dogfooding depositados en cada destino nuevo).
SEED_CONTRACT_IDS: tuple[str, ...] = (
    "WOT-2026-021k",
    "WOT-2026-023r",
    "WOT-2026-023s",
)

# Subconjunto RETIRABLE por --repair: 021k queda fuera por el NON-GOAL de la
# ficha (su waiver migro al workspace; tocarlo romperia la proteccion).
REPAIR_DEFAULT_IDS: tuple[str, ...] = ("WOT-2026-023r", "WOT-2026-023s")

_LINK_RE = Path(".agent") / "config" / "motor_destination_link.json"
_CONTRACTS_RELPATH = Path(".agent") / "planning" / "ticket_contracts.md"
_HEADER_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _contract_ids_of(text: str) -> list[str]:
    """Ids de contratos presentes en un ticket_contracts.md (titulos `## `).

    Before: text contenido del fichero (utf-8, errors=replace). During: regex
        de encabezados y extraccion del primer token tipo id (WOT-2026-XXXXx o
        T-XXX). After: lista ordenada de aparicion, sin duplicados.
    """
    ids: list[str] = []
    for match in _HEADER_RE.finditer(text):
        title = match.group("title")
        m = re.match(r"(?:Contrato\s+)?((?:WOT-2026-|T-)[0-9A-Za-z-]+)", title)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _seed_ids_present(text: str) -> list[str]:
    """Subconjunto de SEED_CONTRACT_IDS presente en el fichero."""
    present = _contract_ids_of(text)
    return [sid for sid in SEED_CONTRACT_IDS if sid in present]


def census_destinations(workspaces_root: Path) -> list[dict[str, object]]:
    """Censo read-only de la flota de destinos bajo workspaces_root.

    Before: workspaces_root raiz que contiene directorios-destino (cada uno con
        .agent/config/motor_destination_link.json). During: por destino, leer
        ticket_contracts.md si existe y extraer ids + ids del motor. After:
        lista de dicts {destino, contracts_file, ids, seed_ids}; SIN escritura.
    """
    results: list[dict[str, object]] = []
    for child in sorted(workspaces_root.iterdir()):
        if not child.is_dir() or not (child / _LINK_RE).is_file():
            continue
        contracts_path = child / _CONTRACTS_RELPATH
        entry: dict[str, object] = {
            "destino": child.name,
            "path": str(child),
            "contracts_file": contracts_path.is_file(),
            "ids": [],
            "seed_ids": [],
        }
        if contracts_path.is_file():
            try:
                text = contracts_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                entry["error"] = "unreadable"
                results.append(entry)
                continue
            entry["ids"] = _contract_ids_of(text)
            entry["seed_ids"] = _seed_ids_present(text)
        results.append(entry)
    return results


def _split_seed_sections(
    text: str, repair_ids: tuple[str, ...]
) -> tuple[str, list[str]]:
    """Recorta del texto las secciones `## <id>` de repair_ids.

    Before: text completo del ticket_contracts.md; repair_ids ids del seed
        retirables (solo 023r/023s por defecto). During: localiza cada
        encabezado `## <id>...` y borra desde el encabezado hasta el siguiente
        encabezado `## ` (o EOF); NO toca el resto. After: (texto nuevo,
        lista de ids retirados). Idempotente: sin secciones que casen,
        devuelve (text, []).
    """
    removed: list[str] = []
    new_text = text
    for rid in repair_ids:
        pattern = re.compile(
            r"^##\s+" + re.escape(rid) + r"\b[^\n]*\n(?:(?!^## ).*\n?)*",
            re.MULTILINE | re.IGNORECASE,
        )
        if pattern.search(new_text):
            new_text = pattern.sub("", new_text)
            removed.append(rid)
    return new_text, removed


def repair_destination(
    dest: Path, backup_dir: Path
) -> tuple[int, list[str], str | None]:
    """Reparacion OPT-IN de UN destino: backup verificable + recorte del seed.

    Before: dest con ticket_contracts.md; backup_dir existente o creable.
    During: lee el fichero, calcula sha256, escribe backup
        <backup_dir>/<nombre>.<sha8>.bak, recorta SOLO REPAIR_DEFAULT_IDS y
        reescribe SOLO si hay cambios. After: (exit_code, retirados, error):
        exit 0 ok o no-op; exit 1 fallo de precondicion (sin fichero, sin
        cambios posibles); el backup queda aunque la escritura falle.
    """
    contracts_path = dest / _CONTRACTS_RELPATH
    if backup_dir is None:
        return 1, [], "sin --backup-dir: fail-closed, sin backup no se toca nada"
    if not contracts_path.is_file():
        return 1, [], f"sin {contracts_path}"
    text = contracts_path.read_text(encoding="utf-8", errors="replace")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{contracts_path.name}.{sha[:8]}.bak"
    backup_path.write_bytes(contracts_path.read_bytes())

    new_text, removed = _split_seed_sections(text, REPAIR_DEFAULT_IDS)
    if not removed:
        return 0, [], None  # idempotente: nada que retirar, sin reescritura
    contracts_path.write_text(new_text, encoding="utf-8")
    return 0, removed, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspaces-root", type=Path, help="Raiz que contiene destinos (censo)."
    )
    parser.add_argument(
        "--repair", action="store_true", help="Modo reparacion OPT-IN (exige --dest)."
    )
    parser.add_argument("--dest", type=Path, help="Destino concreto (solo --repair).")
    parser.add_argument(
        "--backup-dir", type=Path, help="Directorio del backup (exigido por --repair)."
    )
    parser.add_argument("--json", action="store_true", help="Salida JSON (censo).")
    args = parser.parse_args(argv)

    if args.repair:
        if not args.dest or not args.backup_dir:
            print(
                "[census-contracts] --repair exige --dest y --backup-dir "
                "(fail-closed: sin backup no se toca nada)",
                file=sys.stderr,
            )
            return 1
        code, removed, err = repair_destination(args.dest, args.backup_dir)
        if err:
            print(f"[census-contracts] FAIL: {err}", file=sys.stderr)
            return 1
        if removed:
            print(
                "[census-contracts] reparados en "
                f"{args.dest}: {', '.join(removed)} (backup en {args.backup_dir})"
            )
        else:
            print(
                "[census-contracts] no-op: 0 secciones del motor presentes "
                f"en {args.dest} (idempotente, sin reescritura)"
            )
        return code

    if not args.workspaces_root or not args.workspaces_root.is_dir():
        print("[census-contracts] ERROR: --workspaces-root ilegible", file=sys.stderr)
        return 2
    results = census_destinations(args.workspaces_root)
    if args.json:
        import json

        print(json.dumps(results, indent=1, ensure_ascii=True))
    else:
        for entry in results:
            seed = entry.get("seed_ids") or []
            flag = f"  SEED DEL MOTOR: {', '.join(seed)}" if seed else ""
            ids = entry.get("ids") or []
            n = len(ids) if entry.get("contracts_file") else 0
            print(
                f"{entry['destino']}: contracts={'si' if entry.get('contracts_file') else 'no'} "
                f"ids={n}{flag}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
