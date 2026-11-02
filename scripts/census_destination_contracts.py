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
  - EXIGE --backup-dir y crea ahi, en modo EXCLUSIVO, una copia (sha256 en el
    nombre) del fichero ANTES de tocar nada, la relee sin seguir enlaces y
    comprueba su sha antes de escribir (fail-closed: sin backup verificado no
    se toca nada). Un backup del mismo nombre ya existente solo se reutiliza
    si es un fichero regular con los mismos bytes; si es enlace, directorio o
    contenido distinto, rc 1 sin escribir.
  - Retira SOLO las secciones de contratos del motor cuyo id este en
    REPAIR_DEFAULT_IDS (023r/023s) Y cuya POSICION pertenezca a la cadena
    contigua que sigue al bloque `## MIGRACION DESDE repo_motor`. WOT-2026-021k
    queda EXCLUIDO por defecto: su waiver migro al workspace y el NON-GOAL de
    la ficha lo protege.
  - IDEMPOTENTE: una segunda pasada sobre lo ya reparado es no-op (0 secciones
    retiradas) y no reescribe el fichero si no hay cambios.
  - Regla POSICIONAL, no garantia universal: se conserva (y se nombra) todo id
    de seed fuera de la cadena contigua, repetido dentro de ella, o en un
    fichero no UTF-8. LIMITE: un contrato del destino cuyo id de seed quede
    UNICO dentro de la cadena contigua es indistinguible por posicion de uno
    del motor y SE RETIRA (con backup verificado).
  - La escritura final es por temporal exclusivo y no previsible (mkstemp) en
    el mismo directorio + os.replace; nunca sigue una entrada preexistente.

Before: raices legibles. During: lectura + regex de encabezados `## ` y recorte
de secciones; escritura SOLO en --repair y solo tras backup verificado. After:
censo imprime tabla y exit 0 (o 2 infra); --repair imprime lo retirado y sale 0
(con cambios o no-op) o 1 si falla una precondicion, el backup, la decodificacion
UTF-8 o la escritura (el original queda intacto). NO re-examina el destino tras
reparar ni sale 1 por ids del motor que sigan presentes: el aviso de lo
conservado va por stdout y el operador relanza el censo.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
import tempfile
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


def _origin_verified_indices(
    headers: list[tuple[int, str, str | None]],
) -> set[int]:
    """Indices de header con marca de origen demostrada POR POSICION.

    Before: headers (posicion, titulo, id-o-None) en orden. During: busca el
        primer header cuyo titulo cite MIGRACION y repo_motor (DEC-024H-001)
        y propaga la marca SOLO por el bloque CONTIGUO de secciones con id del
        seed que le sigue; una seccion de otro id corta la cadena. La marca
        es del INDICE del header, no del id: un contrato del DESTINO con el
        mismo id escrito antes del bloque o tras el corte NO la hereda. Un id
        repetido DENTRO de la cadena es ambiguo (no se sabe cual es del motor):
        ninguna de sus apariciones queda verificada. Solo cuenta el primer
        bloque MIGRACION; un segundo grupo no hereda marca.
    After: conjunto de indices (en headers) con origen demostrado.
    """
    for i, (_start, title, _cid) in enumerate(headers):
        if "MIGRACION" not in title or "repo_motor" not in title:
            continue
        chain: list[int] = []
        for j in range(i + 1, len(headers)):
            following = headers[j][2]
            if following is None or following not in SEED_CONTRACT_IDS:
                break
            chain.append(j)
        chain_ids = [headers[j][2] for j in chain]
        return {j for j in chain if chain_ids.count(headers[j][2]) == 1}
    return set()


def _split_seed_sections(
    text: str, repair_ids: tuple[str, ...]
) -> tuple[str, list[str], list[str]]:
    """Recorta del texto las secciones `## <id>` de repair_ids CON marca de origen.

    Before: text completo del ticket_contracts.md; repair_ids ids del seed
        retirables (solo 023r/023s por defecto). During: localiza TODOS los
        encabezados `## ` por posicion (casa `## WOT-2026-XXX`, `## Contrato
        WOT-2026-XXX` y cualquier variante cuyo primer token sea el id), corta
        cada seccion hasta el siguiente encabezado o EOF (sin exigir salto
        final) y retira SOLO las secciones cuyo id este en repair_ids Y cuyo
        POSICION este en la cadena marcada tras el bloque MIGRACION (ver
        _origin_verified_indices) -- un contrato del DESTINO con un id del
        seed se CONSERVA y se reporta. After: (texto nuevo, ids retirados,
        ids con id-de-seed conservados por falta de marca de origen).
        Idempotente: sin secciones que casen, devuelve (text, [], []).
    """
    headers: list[tuple[int, str, str | None]] = []
    for match in _HEADER_RE.finditer(text):
        title = match.group("title")
        m = re.match(r"(?:Contrato\s+)?((?:WOT-2026-|T-)[0-9A-Za-z-]+)", title)
        headers.append((match.start(), title, m.group(1) if m else None))

    # WOT-2026-026o ronda 2: el marcador de origen del seed es el bloque
    # `## MIGRACION DESDE repo_motor` (DEC-024H-001). WOT-2026-152j: la marca
    # se propaga por POSICION (indice de header en la cadena contigua), no por
    # id; ver _origin_verified_indices.
    origin_verified = _origin_verified_indices(headers)

    remove_spans: list[tuple[int, int]] = []
    removed: list[str] = []
    kept_no_origin: list[str] = []
    for i, (start, _title, cid) in enumerate(headers):
        if cid is None or cid not in repair_ids:
            continue
        end = headers[i + 1][0] if i + 1 < len(headers) else len(text)
        # WOT-2026-026o ronda 3 (hallazgo Codex): SIN fallback de marca local.
        # Un titulo que cite repo_motor NO es origen; solo la cadena contigua
        # desde el bloque MIGRACION autoriza el retiro (el caso contrario se
        # conserva y se nombra).
        if i in origin_verified:
            remove_spans.append((start, end))
            removed.append(cid)
        else:
            kept_no_origin.append(cid)

    if not remove_spans:
        return text, [], kept_no_origin
    for start, end in reversed(remove_spans):
        text = text[:start] + text[end:]
    return text, removed, kept_no_origin


def _write_atomic(path: Path, data: bytes) -> None:
    """Escribe data en path por temporal hermano + os.replace.

    Before: path en un directorio escribible. During: crea con tempfile.mkstemp
        (O_EXCL, nombre no previsible) un temporal en el MISMO directorio, lo
        escribe y lo mueve sobre path; nunca sigue una entrada preexistente.
    After: path con el contenido nuevo; si algo falla, path queda intacto, SOLO
        el temporal propio se borra y se propaga el OSError.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".census-tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _read_regular(path: Path) -> bytes | None:
    """Bytes de path si es un fichero REGULAR (lstat, sin seguir enlaces).

    Before: path existente o no. During: lstat + read_bytes. After: los bytes,
        o None si path es enlace simbolico, directorio u otra cosa; un OSError
        (ausente, sin permiso) se propaga al llamador.
    """
    if not stat.S_ISREG(os.lstat(path).st_mode):
        return None
    return path.read_bytes()


def _write_verified_backup(
    backup_dir: Path, name: str, raw: bytes
) -> tuple[Path | None, str | None]:
    """Crea <backup_dir>/<name>.<sha8>.bak en modo EXCLUSIVO y comprueba su sha.

    Before: raw son los BYTES ORIGINALES del fichero (el sha no se calcula
        sobre texto normalizado). During: mkdir + open(`xb`) (no sigue ni pisa
        una entrada preexistente) + relectura sin seguir enlaces. Un backup
        PREEXISTENTE solo se reutiliza si es un fichero regular con los mismos
        bytes; enlace, directorio o contenido distinto = error (no se elige
        un nombre alternativo ni se pisa nada).
    After: (ruta, None) si el backup existe y su sha coincide; (None, error)
        en cualquier otro caso. No escribe nada mas.
    """
    sha = hashlib.sha256(raw).hexdigest()
    backup_path = backup_dir / f"{name}.{sha[:8]}.bak"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(backup_path, "xb") as fh:
                fh.write(raw)
        except FileExistsError:
            pass  # preexistente: se valida abajo (regular e identico o error)
        on_disk = _read_regular(backup_path)
        if on_disk is None:
            return None, f"backup preexistente no es fichero regular: {backup_path}"
        if hashlib.sha256(on_disk).hexdigest() != sha:
            return None, f"backup no verificable (sha distinto): {backup_path}"
    except OSError as exc:
        return None, f"backup fallido, no se toca nada: {exc}"
    return backup_path, None


def repair_destination(
    dest: Path, backup_dir: Path
) -> tuple[int, list[str], str | None]:
    """Reparacion OPT-IN de UN destino: backup verificable + recorte del seed.

    Before: dest con ticket_contracts.md; backup_dir existente o creable.
    During: lee el fichero, calcula sha256, escribe backup
        <backup_dir>/<nombre>.<sha8>.bak, lo relee y comprueba su sha ANTES de
        decodificar o escribir nada; decodifica en UTF-8 estricto; recorta
        SOLO REPAIR_DEFAULT_IDS y reescribe SOLO si hay cambios, por temporal
        en el mismo directorio + os.replace. After: (exit_code, retirados,
        error): exit 0 ok o no-op; exit 1 si falla una precondicion (sin
        fichero, enlace simbolico), el backup (escritura o sha), la
        decodificacion UTF-8 o la escritura; en todo exit 1 el original queda
        INTACTO (sin temporal residual) y el backup, si llego a crearse, queda.
    """
    contracts_path = dest / _CONTRACTS_RELPATH
    if backup_dir is None:
        return 1, [], "sin --backup-dir: fail-closed, sin backup no se toca nada"
    if not contracts_path.is_file():
        return 1, [], f"sin {contracts_path}"
    if contracts_path.is_symlink():
        # os.replace sustituiria el enlace por un fichero regular: se rechaza.
        return 1, [], f"{contracts_path} es un enlace simbolico: no se toca"
    # WOT-2026-026o ronda 2 (hallazgo Codex): el sha del backup se calcula
    # sobre los BYTES ORIGINALES (read_text normaliza CRLF y el hash dejaria
    # de ser verificable contra el backup).
    try:
        raw = contracts_path.read_bytes()
    except OSError as exc:
        return 1, [], f"no se pudo leer {contracts_path}: {exc}"
    backup_path, backup_err = _write_verified_backup(
        backup_dir, contracts_path.name, raw
    )
    if backup_err or backup_path is None:
        return 1, [], backup_err

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return (
            1,
            [],
            f"{contracts_path} no es UTF-8: no se reescribe (backup en {backup_path})",
        )
    new_text, removed, kept_no_origin = _split_seed_sections(text, REPAIR_DEFAULT_IDS)
    if kept_no_origin:
        # WOT-2026-026o ronda 2: id del seed SIN marca de origen = probable
        # contrato del destino; se conserva y se nombra (nunca silencio).
        print(
            "[census-contracts] AVISO: secciones con id del seed CONSERVADAS "
            f"por falta de marca de origen: {', '.join(kept_no_origin)}"
        )
    if not removed:
        return 0, [], None  # idempotente: nada que retirar, sin reescritura
    try:
        _write_atomic(contracts_path, new_text.encode("utf-8"))
    except OSError as exc:
        return 1, [], f"escritura fallida, original intacto: {exc}"
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
    try:
        results = census_destinations(args.workspaces_root)
    except OSError as exc:
        print(f"[census-contracts] ERROR: raiz no listable: {exc}", file=sys.stderr)
        return 2
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
