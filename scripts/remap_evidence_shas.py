#!/usr/bin/env python3
r"""Remapea el `commit_sha` de la evidencia de bucles tras reescribir historia.

DOCTRINA
--------
`scorecard.jsonl` y `emitted_nonces.jsonl` atan cada ronda de un bucle de
gobierno a un `commit_sha`, y `scripts/check_loop_execution.py` compara ese
campo por IGUALDAD EXACTA. Tras reescribir historia (amend, rebase,
filter-repo) las filas siguen citando el sha viejo, el commit nuevo queda con
0 rondas y el cierre falla sin decir por que. Esta es la salida de
autoservicio: remapea SOLO pares OLD=NEW que el OPERADOR aporta a mano
(`--map`, repetible) y SOLO tras verificar contra git que ambos commits son el
MISMO cambio: mismo arbol (`git rev-parse <sha>^{tree}`) Y mismo patch-id
(`git patch-id --stable`). Un par que no se puede verificar se RECHAZA y no se
toca: la herramienta no atestigua lo que nadie reviso (NG-RAIZ: no descubre
pares por heuristica ni expande abreviados por prefijo).

CONTRATO OPERATIVO (T-088B-001)
-------------------------------
- DRY-RUN POR DEFECTO: sin `--apply` no se escribe NADA (ni copias ni mapa).
- Sustitucion a nivel de BYTES: solo cambia el valor exacto del campo
  `commit_sha`; los finales de linea mixtos (CRLF/LF), el orden de las filas,
  las filas sin `commit_sha`, las lineas no-JSON y el UTF-8 crudo quedan
  intactos. El parseo JSON solo CLASIFICA; PROHIBIDO re-serializar.
- Exit codes: 0 ok; 1 algun par rechazado sin `--skip-rejected` (no escribe
  nada); 2 uso invalido, I/O, fichero de evidencia ausente o denominador
  `inspeccionadas == 0`.
- `--apply`: copia `<nombre>.pre-remap.<ts>` (UTC con microsegundos, modo
  EXCLUSIVO) en `<destino>/.agent/runtime/ensemble/remap/`, escribe cada
  fichero a un temporal del mismo directorio y lo reemplaza con `os.replace`;
  si falla el segundo fichero RESTAURA el primero; un
  `remap_<ts>.inprogress.json` cubre el corte duro entre los dos reemplazos y
  su residuo hace salir con 2 pidiendo restauracion MANUAL (no decide sola).
- REESCRIBE unicamente `scorecard.jsonl` y `emitted_nonces.jsonl`; cualquier
  aparicion de un OLD remapeado en el INVENTARIO declarado se LISTA
  (`referencias_externas`) y NUNCA se reescribe.

RIESGO RESIDUAL DECLARADO
-------------------------
La ventana entre la comprobacion de concurrencia (tamano+sha256) y el
`os.replace` NO es cero. NO lances bucles de ensemble durante `--apply`: los
escritores del ledger usan `_locked_for_append` (`ensemble_dispatch.py:1629`)
y este reemplazo no participa de ese lock.

ALCANCE (WOT-2026-079a)
-----------------------
Solo los DOS ficheros ACTIVOS; los scorecards rotados/archivados no se leen
ni se remapean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

SCORECARD_REL = Path(".agent/runtime/ensemble/scorecard.jsonl")
EMITTED_NONCES_REL = Path(".agent/runtime/ensemble/emitted_nonces.jsonl")
REMAP_DIR_REL = Path(".agent/runtime/ensemble/remap")

EXTERNAL_REFERENCE_FILES = (
    "fallback_events.jsonl",
    "adversarial_findings_raw.jsonl",
    "backend_leaders.json",
    "backend_family_leaders.json",
    "backend_status.json",
    "backend_quarantine.json",
)

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2

REJECTED_PREFIX = "rechazado:"


class _ConcurrentWriteError(RuntimeError):
    """El fichero de evidencia cambio entre la lectura inicial y el reemplazo."""


def _utc_stamp() -> str:
    """Sello UTC con microsegundos: `YYYYMMDDTHHMMSSffffffZ` (D8)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _fingerprint(path: Path) -> tuple[int, str]:
    """(tamano, sha256) del fichero, leido en binario."""
    raw = path.read_bytes()
    return (len(raw), hashlib.sha256(raw).hexdigest())


def _git_run(
    git_root: Path, args: list[str], input_bytes: bytes | None = None
) -> subprocess.CompletedProcess | None:
    """Ejecuta git en BYTES (sin shell ni pipes): un pipe re-codifica el diff."""
    try:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(git_root), *args],  # noqa: S607
            input=input_bytes,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _classify_batch_line(line: str) -> tuple[str, str | None]:
    """Clasifica UNA linea de `cat-file --batch-check` en (estado, sha40).

    Estados: `commit` (resuelve a commit), `ambiguous` (abreviatura multiple),
    `missing` (no resuelve) y `peel` (existe pero no es commit: arbol/blob/tag;
    un tag puede pelear a commit en una segunda pasada).
    """
    parts = line.split()
    kind = parts[1] if len(parts) >= 2 else ""
    if kind == "commit":
        return "commit", parts[0]
    if kind == "ambiguous":
        return "ambiguous", None
    if kind in ("tree", "blob", "tag"):
        return "peel", None
    return "missing", None


def _run_batch(git_root: Path, payload: bytes, expected: int) -> list[str] | None:
    """Una lectura batch-check; None si git fallo o la salida no correlaciona."""
    proc = _git_run(git_root, ["cat-file", "--batch-check"], payload)
    if proc is None or proc.returncode != 0:
        return None
    lines = proc.stdout.decode("utf-8", errors="replace").splitlines()
    if len(lines) < expected:
        return None
    return lines


def _fill_from_batch(
    results: dict[str, tuple[str, str | None]],
    query: list[str],
    lines: list[str] | None,
) -> list[str]:
    """Vuelca una tanda batch en `results`; devuelve los que requieren peel.

    `lines is None` (git fallo o no correlaciona) marca toda la tanda `error`.
    """
    if lines is None:
        for sha in query:
            results[sha] = ("error", None)
        return []
    pending: list[str] = []
    for sha, line in zip(query, lines, strict=False):
        kind, sha40 = _classify_batch_line(line)
        if kind == "peel":
            pending.append(sha)
        else:
            results[sha] = (kind, sha40)
    return pending


def _lookup_objects(
    git_root: Path, shas: list[str]
) -> dict[str, tuple[str, str | None]]:
    """Resuelve sha -> (estado, sha40) con UN `cat-file --batch-check` en lote.

    El lookup va SIN `^{commit}` a proposito: el peel convierte la ambiguedad
    en `missing` y perderia el estado `rechazado:ambiguo`; los tags se peelan
    en una segunda pasada. `error` cubre git no ejecutable, rc != 0, salida no
    parseable o un sha con espacios.
    """
    results: dict[str, tuple[str, str | None]] = {}
    query: list[str] = []
    for sha in shas:
        if not sha or any(ch.isspace() for ch in sha):
            results[sha] = ("error", None)
        else:
            query.append(sha)
    if not query:
        return results
    payload = b"".join(s.encode() + b"\n" for s in query)
    pending_peel = _fill_from_batch(
        results, query, _run_batch(git_root, payload, len(query))
    )
    if not pending_peel:
        return results
    payload = b"".join(f"{s}^{{commit}}\n".encode() for s in pending_peel)
    _fill_from_batch(
        results, pending_peel, _run_batch(git_root, payload, len(pending_peel))
    )
    for sha in pending_peel:
        state = results.get(sha, ("error", None))[0]
        if state not in ("commit", "error"):
            results[sha] = ("missing", None)
    return results


def _compare_trees(
    git_root: Path, old_full: str, new_full: str
) -> tuple[str | None, str | None, str | None]:
    """Mismo arbol? (estado_rechazo | None, old_tree, new_tree)."""
    trees: dict[str, str] = {}
    for sha in (old_full, new_full):
        proc = _git_run(git_root, ["rev-parse", f"{sha}^{{tree}}"])
        if proc is None or proc.returncode != 0:
            return f"{REJECTED_PREFIX}error_git", None, None
        trees[sha] = proc.stdout.decode("utf-8", errors="replace").strip()
    if trees[old_full] != trees[new_full]:
        return f"{REJECTED_PREFIX}arbol_distinto", None, None
    return None, trees[old_full], trees[new_full]


def _first_patch_id(stdout: bytes) -> str:
    """Primer token de la primera linea con contenido (`<patch-id> <commit>`)."""
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if parts and parts[0]:
            return parts[0]
    return ""


def _compare_patch_ids(git_root: Path, old_full: str, new_full: str) -> str | None:
    """Mismo patch-id (`--stable`)? Un patch-id vacio NUNCA se admite."""
    patch_ids: dict[str, str] = {}
    for sha in (old_full, new_full):
        show = _git_run(git_root, ["show", sha])
        if show is None or show.returncode != 0:
            return f"{REJECTED_PREFIX}error_git"
        proc = _git_run(git_root, ["patch-id", "--stable"], show.stdout)
        if proc is None or proc.returncode != 0:
            return f"{REJECTED_PREFIX}error_git"
        token = _first_patch_id(proc.stdout)
        if not token:
            return f"{REJECTED_PREFIX}patch_id_vacio"
        patch_ids[sha] = token
    if patch_ids[old_full] != patch_ids[new_full]:
        return f"{REJECTED_PREFIX}patch_id_distinto"
    return None


def _metadata_differs(git_root: Path, old_full: str, new_full: str) -> bool | None:
    """True/False si mensaje/autor/fecha/padres difieren; None si git fallo.

    Solo se descarta la CABECERA `tree <sha>` (primera linea del objeto commit):
    una linea del MENSAJE que empiece por `tree ` es contenido y debe contar.
    """
    raws: dict[str, bytes] = {}
    for sha in (old_full, new_full):
        proc = _git_run(git_root, ["cat-file", "commit", sha])
        if proc is None or proc.returncode != 0:
            return None
        lines = proc.stdout.split(b"\n")
        if lines and lines[0].startswith(b"tree "):
            lines = lines[1:]
        raws[sha] = b"\n".join(lines)
    return raws[old_full] != raws[new_full]


def _validate_pair(
    git_root: Path, old: str, new: str
) -> tuple[str | None, str | None, bool | None]:
    """Valida un par contra git: (estado_rechazo | None, old_full, metadatos).

    Orden D2: resolucion `<sha>^{commit}` > arbol > patch-id > metadatos.
    """
    results = _lookup_objects(git_root, [old, new])
    for sha in (old, new):
        state, _full = results.get(sha, ("error", None))
        if state == "ambiguous":
            return f"{REJECTED_PREFIX}ambiguo", None, None
        if state == "missing":
            return f"{REJECTED_PREFIX}objeto_inexistente", None, None
        if state != "commit":
            return f"{REJECTED_PREFIX}error_git", None, None
    old_full = results[old][1] or old
    new_full = results[new][1] or new
    estado, _tree_old, _tree_new = _compare_trees(git_root, old_full, new_full)
    if estado:
        return estado, None, None
    estado = _compare_patch_ids(git_root, old_full, new_full)
    if estado:
        return estado, None, None
    metadatos = _metadata_differs(git_root, old_full, new_full)
    if metadatos is None:
        return f"{REJECTED_PREFIX}error_git", None, None
    return None, old_full, metadatos


def _parse_json(segment: bytes) -> tuple[bool, object]:
    """(parsea?, valor). El parseo JSON solo CLASIFICA, jamas escribe."""
    try:
        return True, json.loads(segment.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, None


def _value_pattern(old: str) -> re.Pattern[bytes]:
    """Patron de bytes del valor: `"commit_sha"`, espacios, `:`, espacios, `"OLD"`."""
    return re.compile(
        rb'("commit_sha"\s*:\s*")(' + re.escape(old.encode("utf-8")) + rb')(")'
    )


def _scan_segments(segments: list[bytes], olds: list[str]) -> dict:
    """Pasada unica de clasificacion por fichero (denominador + candidatos).

    Before: `segments` es el fichero partido por `\\n` (finales de linea
        intactos en el segmento previo); `olds` los OLD de los pares.
    During: puro; no escribe. Las lineas no-JSON solo se inspeccionan si
        contienen algun OLD (se listan como `linea_no_json_con_old`).
    After: dict con denominador por fichero, candidatos por OLD (indices),
        lineas no-JSON con OLD y la lista ordenada de `commit_sha` distintos
        (primera aparicion) para el censo de huerfanos.
    """
    old_bytes = {old: old.encode("utf-8") for old in olds}
    candidatos: dict[str, list[int]] = {old: [] for old in olds}
    no_json_con_old: list[dict] = []
    shas_orden: list[str] = []
    visto: set[str] = set()
    contadores = {"inspeccionadas": 0, "con_commit_sha": 0, "sin_commit_sha": 0}
    no_afectadas = 0
    for idx, segment in enumerate(segments):
        if not segment.strip():
            continue
        contadores["inspeccionadas"] += 1
        ok, row = _parse_json(segment)
        if not ok:
            for old, needle in old_bytes.items():
                if needle in segment:
                    no_json_con_old.append({"linea": idx + 1, "old": old})
            contadores["sin_commit_sha"] += 1
            continue
        sha = row.get("commit_sha") if isinstance(row, dict) else None
        if isinstance(sha, str) and sha:
            contadores["con_commit_sha"] += 1
            if sha not in visto:
                visto.add(sha)
                shas_orden.append(sha)
            if sha in candidatos:
                candidatos[sha].append(idx)
            else:
                no_afectadas += 1
        else:
            contadores["sin_commit_sha"] += 1
    return {
        **contadores,
        "no_afectadas": no_afectadas,
        "candidatos": candidatos,
        "no_json_con_old": no_json_con_old,
        "shas_orden": shas_orden,
    }


def _rewrite_segments(
    segments: list[bytes],
    remap_pairs: dict[str, str],
    old_fulls: dict[str, str],
) -> tuple[list[bytes], int, list[dict], list[dict]]:
    """Sustituye a nivel de BYTES solo el valor exacto de `commit_sha`.

    Una fila se modifica SOLO si parsea como JSON, su `commit_sha` de primer
    nivel es exactamente OLD y el patron aparece UNA vez en la linea; si no,
    queda intacta y se lista (`fila_ambigua`). Los bytes restantes, el orden,
    los finales de linea y el UTF-8 crudo se conservan.
    """
    nuevos = list(segments)
    remapeadas = 0
    fila_ambigua: list[dict] = []
    abreviados: list[dict] = []
    patrones = {old: _value_pattern(old) for old in remap_pairs}
    for idx, segment in enumerate(segments):
        if not segment.strip():
            continue
        ok, row = _parse_json(segment)
        if not ok or not isinstance(row, dict):
            continue
        sha = row.get("commit_sha")
        if not isinstance(sha, str) or not sha:
            continue
        if sha in remap_pairs:
            matches = list(patrones[sha].finditer(segment))
            if len(matches) == 1:
                match = matches[0]
                nuevos[idx] = (
                    segment[: match.start(2)]
                    + remap_pairs[sha].encode("utf-8")
                    + segment[match.end(2) :]
                )
                remapeadas += 1
            else:
                fila_ambigua.append({"linea": idx + 1, "old": sha})
            continue
        for old, full in old_fulls.items():
            if full and sha != old and (sha == full or full.startswith(sha)):
                abreviados.append({"linea": idx + 1, "commit_sha": sha, "old": old})
                break
    return nuevos, remapeadas, fila_ambigua, abreviados


def _find_orphans(git_root: Path, project_root: Path, shas: list[str]) -> list[str]:
    """SHAs de la evidencia que no resuelven en NINGUNA raiz (D6)."""
    if not shas:
        return []
    roots = [git_root]
    if project_root.resolve() != git_root.resolve():
        roots.append(project_root)
    resolubles: set[str] = set()
    for root in roots:
        results = _lookup_objects(root, shas)
        resolubles |= {
            sha for sha, (state, _full) in results.items() if state == "commit"
        }
    return [sha for sha in shas if sha not in resolubles]


def _scan_external_references(
    project_root: Path, remap_pairs: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    """LISTA (nunca reescribe) apariciones de un OLD en el inventario (D5)."""
    refs: list[dict] = []
    saltados: list[dict] = []
    base = project_root / ".agent/runtime/ensemble"
    for name in EXTERNAL_REFERENCE_FILES:
        path = base / name
        if not path.is_file():
            saltados.append({"fichero": name, "razon": "ausente"})
            continue
        raw = path.read_bytes()
        for old in remap_pairs:
            count = raw.count(old.encode("utf-8"))
            if count:
                refs.append({"fichero": name, "old": old, "ocurrencias": count})
    return refs, saltados


def _exclusive_write(path: Path, data: bytes) -> None:
    """Crea `path` en modo EXCLUSIVO; si ya existe, `FileExistsError`."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _write_bytes(path: Path, data: bytes) -> None:
    """Escritura binaria simple; seam unico para inyectar fallos de I/O."""
    with open(path, "wb") as handle:
        handle.write(data)


def _replace_file(path: Path, data: bytes) -> None:
    """Escribe a un temporal del MISMO directorio y `os.replace` (atomico)."""
    tmp = path.with_name(f"{path.name}.tmp-remap-{os.getpid()}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _verify_unchanged(path: Path, expected: tuple[int, str]) -> None:
    """Aborta si otro proceso escribio el fichero desde la lectura inicial."""
    if _fingerprint(path) != expected:
        raise _ConcurrentWriteError(
            f"otro proceso escribio {path.name} (tamano/sha256 distintos)"
        )


def _restore(path: Path, copy: Path) -> None:
    """Restaura `path` desde su copia `pre-remap`."""
    _replace_file(path, copy.read_bytes())


def _report_inprogress_error(remap_dir: Path, residual: list[Path]) -> None:
    """Explica la restauracion MANUAL y las copias implicadas (D8)."""
    print(
        f"[remap] ERROR: existe un remap sin cerrar en {remap_dir} "
        f"({len(residual)} fichero(s) *.inprogress.json).",
        file=sys.stderr,
    )
    for path in residual:
        try:
            payload = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        print(f"[remap]   sentinela: {path}", file=sys.stderr)
        for entry in payload.get("ficheros", []):
            print(
                f"[remap]   RESTAURACION MANUAL: copia {entry.get('copia')} "
                f"sobre {entry.get('fichero')}",
                file=sys.stderr,
            )
    print(
        "[remap]   La herramienta NO restaura sola: resuelve la copia a mano y "
        "borra el sentinela antes de reintentar.",
        file=sys.stderr,
    )


def _unlink_quiet(path: Path, what: str) -> None:
    """Borra `path` sin propagar: un fallo se reporta como WARN."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"[remap] WARN: no pude borrar {what} {path}: {exc}", file=sys.stderr)


def _cleanup_copies(copies: list[Path]) -> None:
    """Borra SOLO copias creadas por ESTA ejecucion (jamas una copia previa)."""
    for copy in copies:
        _unlink_quiet(copy, "la copia")


def _remove_sentinel(sentinel: Path) -> None:
    """Borra el sentinela; si no puede, lo dice (bloqueara el proximo apply)."""
    try:
        sentinel.unlink(missing_ok=True)
    except OSError as exc:
        print(
            f"[remap] WARN: no pude borrar el sentinela {sentinel}: {exc}; un "
            f"--apply posterior se negara hasta que se resuelva a mano",
            file=sys.stderr,
        )


def _restore_or_report(path: Path, copy: Path) -> bool:
    """Restaura `path` desde `copy`; un fallo se reporta y devuelve False."""
    try:
        _restore(path, copy)
        return True
    except OSError as exc:
        print(
            f"[remap] ERROR: no pude restaurar {path}; se CONSERVA su copia "
            f"{copy}: {exc}",
            file=sys.stderr,
        )
        return False


def _rollback(
    replaced: list[Path],
    copies: dict[Path, Path],
    created_copies: list[Path],
    sentinel: Path,
) -> None:
    """Rollback de un apply abortado: restaura, borra sentinela y limpia copias.

    Un fallo al restaurar NO propaga (se reporta): ese fichero CONSERVA su copia
    como red de recuperacion manual. El resto de copias creadas en esta
    ejecucion se borran (D8: un apply abortado no deja artefactos huerfanos).
    """
    failed: set[Path] = set()
    for path in reversed(replaced):
        if not _restore_or_report(path, copies[path]):
            failed.add(path)
    _remove_sentinel(sentinel)
    keep = {copies[path] for path in failed}
    _cleanup_copies([copy for copy in created_copies if copy not in keep])


def _apply_changes(
    project_root: Path,
    stamp: str,
    changes: dict[Path, bytes],
    originals: dict[Path, bytes],
    initial_fingerprints: dict[Path, tuple[int, str]],
    report: dict,
) -> int:
    """Aplica los reemplazos con copia previa y restauracion (D8).

    Before: `changes` solo contiene ficheros con bytes REALMENTE distintos;
        los ficheros estan fuera de `remap/` y la comprobacion de sentinel
        residual ya paso en `main`.
    During: crea `<nombre>.pre-remap.<ts>` exclusivo por fichero, escribe el
        sentinela, verifica tamano+sha256 antes de cada `os.replace` y
        reemplaza. TODA excepcion (copia N, sentinela, reemplazo, restore del
        rollback, informe) se captura: nunca escapa una traza y nunca quedan
        copias huerfanas de ESTA ejecucion (la copia de un fichero cuyo restore
        fallo se conserva, con su ruta reportada).
    After: `EXIT_OK` con `remap_<ts>.json` escrito, o `EXIT_USAGE` con los
        ficheros restaurados y `remap/` sin residuos de esta ejecucion.
    """
    remap_dir = project_root / REMAP_DIR_REL
    try:
        remap_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[remap] ERROR: no pude crear {remap_dir}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    copies: dict[Path, Path] = {}
    created_copies: list[Path] = []
    for path in changes:
        copy = remap_dir / f"{path.name}.pre-remap.{stamp}"
        try:
            _exclusive_write(copy, originals[path])
        except FileExistsError:
            _cleanup_copies(created_copies)
            print(
                f"[remap] ERROR: la copia ya existe y NUNCA se sobrescribe: {copy}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        except OSError as exc:
            _cleanup_copies(created_copies)
            print(
                f"[remap] ERROR: no pude crear la copia {copy}: {exc}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        created_copies.append(copy)
        copies[path] = copy
    sentinel = remap_dir / f"remap_{stamp}.inprogress.json"
    try:
        _write_bytes(
            sentinel,
            json.dumps(
                {
                    "timestamp": stamp,
                    "project_root": str(project_root),
                    "ficheros": [
                        {"fichero": str(path), "copia": str(copy)}
                        for path, copy in copies.items()
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
    except OSError as exc:
        _cleanup_copies(created_copies)
        print(
            f"[remap] ERROR: no pude escribir el sentinela {sentinel}: {exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    replaced: list[Path] = []
    try:
        for path, data in changes.items():
            _verify_unchanged(path, initial_fingerprints[path])
            _replace_file(path, data)
            replaced.append(path)
    except (_ConcurrentWriteError, OSError) as exc:
        _rollback(replaced, copies, created_copies, sentinel)
        print(
            f"[remap] ABORTADO: {exc}. Restaurado lo ya reemplazado; no se "
            f"escribio nada mas.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    report_path = remap_dir / f"remap_{stamp}.json"
    try:
        _write_bytes(
            report_path,
            json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    except OSError as exc:
        _rollback(replaced, copies, created_copies, sentinel)
        print(
            f"[remap] ERROR: no pude escribir {report_path}: {exc}; todo "
            f"restaurado (apply abortado sin efecto).",
            file=sys.stderr,
        )
        return EXIT_USAGE
    _remove_sentinel(sentinel)
    print(f"[remap] artefactos: {report_path}")
    return EXIT_OK


def _parse_maps(raw_maps: list[str]) -> tuple[list[tuple[str, str]], str | None]:
    """Valida los `--map` ANTES de tocar nada; deduplica el mismo par repetido."""
    pairs: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for raw in raw_maps:
        if "=" not in raw:
            return [], f"--map sin '=': {raw!r}"
        old, new = raw.split("=", 1)
        if not old or not new:
            return [], f"--map con OLD o NEW vacio: {raw!r}"
        if old == new:
            return [], f"--map con OLD == NEW: {raw!r}"
        if old in seen and seen[old] != new:
            return [], f"el mismo OLD con dos NEW distintos: {old!r}"
        if old not in seen:
            seen[old] = new
            pairs.append((old, new))
    return pairs, None


def _build_report(
    *,
    stamp: str,
    apply_mode: bool,
    git_root: Path,
    project_root: Path,
    pair_reports: list[dict],
    scan_sc: dict,
    scan_non: dict,
    remap_counts: dict[str, int],
    no_remapeados: dict,
    orphans: list[str],
    refs: list[dict],
    saltados: list[dict],
) -> dict:
    """Ensambla el objeto de `remap_<ts>.json` (esquema D8)."""
    inspeccionadas_total = scan_sc["inspeccionadas"] + scan_non["inspeccionadas"]
    return {
        "timestamp": stamp,
        "git_root": str(git_root),
        "project_root": str(project_root),
        "apply": apply_mode,
        "pares": pair_reports,
        "filas_remapeadas": {
            "scorecard.jsonl": remap_counts["scorecard.jsonl"],
            "emitted_nonces.jsonl": remap_counts["emitted_nonces.jsonl"],
        },
        "no_remapeados": no_remapeados,
        "huerfanos": orphans,
        "referencias_externas": refs,
        "denominador": {
            "inspeccionadas": inspeccionadas_total,
            "inspeccionadas_por_fichero": {
                "scorecard.jsonl": scan_sc["inspeccionadas"],
                "emitted_nonces.jsonl": scan_non["inspeccionadas"],
            },
            "filas_con_commit_sha": scan_sc["con_commit_sha"]
            + scan_non["con_commit_sha"],
            "filas_sin_commit_sha": scan_sc["sin_commit_sha"]
            + scan_non["sin_commit_sha"],
            "filas_remapeadas": sum(remap_counts.values()),
            "filas_no_afectadas": scan_sc["no_afectadas"] + scan_non["no_afectadas"],
            "saltados": saltados,
        },
    }


def _print_report(report: dict, pair_reports: list[dict]) -> None:
    """Informe legible: denominador, pares, huerfanos y verificacion."""
    modo = "--apply" if report["apply"] else "dry-run"
    denom = report["denominador"]
    print(f"[remap] modo: {modo}")
    print(f"[remap] git-root: {report['git_root']}")
    print(f"[remap] project-root: {report['project_root']}")
    remapeados = sum(1 for p in pair_reports if p["estado"] == "remapeado")
    rechazados = sum(1 for p in pair_reports if p["estado"].startswith(REJECTED_PREFIX))
    sin_filas = sum(1 for p in pair_reports if p["estado"] == "sin_filas")
    print(
        f"[remap] pares: {len(pair_reports)} (remapeados: {remapeados}, "
        f"rechazados: {rechazados}, sin_filas: {sin_filas})"
    )
    for par in pair_reports:
        if par["estado"].startswith(REJECTED_PREFIX):
            print(f"NO REMAPEADO {par['old']} -> {par['new']}: {par['estado']}")
        elif par["estado"] == "sin_filas":
            print(
                f"[remap]   SIN_FILAS {par['old']} -> {par['new']}: ninguna fila "
                f"cita ese OLD (no-op, no se valida ni se rechaza)"
            )
        else:
            extra = " (metadatos_distintos)" if par["metadatos_distintos"] else ""
            print(f"[remap]   REMAPEADO {par['old']} -> {par['new']}{extra}")
    print(
        f"[remap] denominador: inspeccionadas={denom['inspeccionadas']} "
        f"filas_con_commit_sha={denom['filas_con_commit_sha']} "
        f"filas_sin_commit_sha={denom['filas_sin_commit_sha']} "
        f"filas_remapeadas={denom['filas_remapeadas']} "
        f"filas_no_afectadas={denom['filas_no_afectadas']}"
    )
    print(
        "[remap] inspeccionadas por fichero: "
        + ", ".join(
            f"{name}={count}"
            for name, count in denom["inspeccionadas_por_fichero"].items()
        )
    )
    print(f"[remap] huerfanos: {len(report['huerfanos'])} {report['huerfanos'][:10]}")
    if report["referencias_externas"]:
        print(
            f"[remap] referencias externas: "
            f"{len(report['referencias_externas'])} (solo se LISTAN)"
        )
        for ref in report["referencias_externas"]:
            print(
                f"[remap]   {ref['fichero']}: old={ref['old']} "
                f"ocurrencias={ref['ocurrencias']}"
            )
    else:
        print("[remap] referencias externas: 0")
    print(f"[remap] saltados: {len(denom['saltados'])}")
    for item in denom["saltados"]:
        print(f"[remap]   {item}")


def _verification_commands(project_root: Path, pairs: list[dict]) -> list[str]:
    """Comandos de verificacion para los pares remapeados (T3/D8)."""
    return [
        "python scripts/check_loop_execution.py --project-root "
        f"{project_root} --commit-sha {par['new']}"
        for par in pairs
        if par["estado"] == "remapeado"
    ]


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    """CLI: dry-run por defecto, `--apply` con copia/atomo y exit 0/1/2."""
    parser = argparse.ArgumentParser(
        description=(
            "Remapea el commit_sha de scorecard.jsonl y emitted_nonces.jsonl "
            "solo para pares OLD=NEW con el MISMO arbol y patch-id."
        ),
        epilog=(
            "NO lances bucles de ensemble durante --apply: la ventana entre la "
            "comprobacion de concurrencia y el reemplazo no es cero."
        ),
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument(
        "--git-root",
        default=str(MOTOR_ROOT),
        help="repo donde se resuelven y validan los SHAs (default: el motor)",
    )
    parser.add_argument(
        "--map",
        action="append",
        dest="maps",
        default=[],
        metavar="OLD=NEW",
        help="par explicito a remapear (repetible); sigue sin --apply no escribe",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-rejected", action="store_true")
    args = parser.parse_args(argv)

    pairs, error = _parse_maps(args.maps)
    if error:
        print(f"[remap] ERROR: {error}", file=sys.stderr)
        return EXIT_USAGE

    project_root = Path(args.project_root).resolve()
    git_root = Path(args.git_root).resolve()
    sc_path = project_root / SCORECARD_REL
    non_path = project_root / EMITTED_NONCES_REL
    for path in (sc_path, non_path):
        if not path.is_file():
            print(
                f"[remap] ERROR: falta el fichero de evidencia: {path}",
                file=sys.stderr,
            )
            return EXIT_USAGE

    remap_dir = project_root / REMAP_DIR_REL
    if args.apply and remap_dir.is_dir():
        residual = sorted(remap_dir.glob("*.inprogress.json"))
        if residual:
            _report_inprogress_error(remap_dir, residual)
            return EXIT_USAGE

    originals = {sc_path: sc_path.read_bytes(), non_path: non_path.read_bytes()}
    initial_fingerprints = {
        path: (len(raw), hashlib.sha256(raw).hexdigest())
        for path, raw in originals.items()
    }
    segments = {path: raw.split(b"\n") for path, raw in originals.items()}
    olds = [old for old, _new in pairs]
    scan_sc = _scan_segments(segments[sc_path], olds)
    scan_non = _scan_segments(segments[non_path], olds)
    if scan_sc["inspeccionadas"] + scan_non["inspeccionadas"] == 0:
        print(
            "[remap] ERROR: denominador cero (inspeccionadas == 0): la "
            "evidencia esta vacia; no hay nada que remapear.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    pair_reports: list[dict] = []
    remap_pairs: dict[str, str] = {}
    old_fulls: dict[str, str] = {}
    for old, new in pairs:
        filas = len(scan_sc["candidatos"][old]) + len(scan_non["candidatos"][old])
        if filas == 0:
            pair_reports.append(
                {
                    "old": old,
                    "new": new,
                    "estado": "sin_filas",
                    "metadatos_distintos": False,
                }
            )
            continue
        estado, old_full, metadatos = _validate_pair(git_root, old, new)
        if estado is None:
            estado = "remapeado"
            remap_pairs[old] = new
            old_fulls[old] = old_full or old
        pair_reports.append(
            {
                "old": old,
                "new": new,
                "estado": estado,
                "metadatos_distintos": bool(metadatos)
                if estado == "remapeado"
                else False,
            }
        )

    remap_counts = {"scorecard.jsonl": 0, "emitted_nonces.jsonl": 0}
    fila_ambigua: list[dict] = []
    abreviados: list[dict] = []
    changes: dict[Path, bytes] = {}
    for path, name in (
        (sc_path, "scorecard.jsonl"),
        (non_path, "emitted_nonces.jsonl"),
    ):
        nuevos, remapeadas, ambiguas, abrev = _rewrite_segments(
            segments[path], remap_pairs, old_fulls
        )
        remap_counts[name] = remapeadas
        fila_ambigua.extend({"fichero": name, **item} for item in ambiguas)
        abreviados.extend({"fichero": name, **item} for item in abrev)
        new_raw = b"\n".join(nuevos)
        if new_raw != originals[path]:
            changes[path] = new_raw

    all_shas: list[str] = []
    seen_shas: set[str] = set()
    for scan in (scan_sc, scan_non):
        for sha in scan["shas_orden"]:
            if sha not in seen_shas:
                seen_shas.add(sha)
                all_shas.append(sha)
    orphans = _find_orphans(git_root, project_root, all_shas)
    refs, saltados_inv = _scan_external_references(project_root, remap_pairs)

    rejected = [
        par for par in pair_reports if par["estado"].startswith(REJECTED_PREFIX)
    ]
    no_remapeados = {
        "pares": rejected,
        "fila_ambigua": fila_ambigua,
        "linea_no_json_con_old": [
            {"fichero": "scorecard.jsonl", **item}
            for item in scan_sc["no_json_con_old"]
        ]
        + [
            {"fichero": "emitted_nonces.jsonl", **item}
            for item in scan_non["no_json_con_old"]
        ],
        "abreviados_que_no_coinciden": abreviados,
    }
    saltados = [
        *saltados_inv,
        *(
            {
                "fichero": item["fichero"],
                "linea": item["linea"],
                "razon": "fila_ambigua",
            }
            for item in fila_ambigua
        ),
        *(
            {
                "fichero": item["fichero"],
                "linea": item["linea"],
                "razon": "linea_no_json_con_old",
            }
            for item in no_remapeados["linea_no_json_con_old"]
        ),
        *(
            {
                "fichero": item["fichero"],
                "linea": item["linea"],
                "razon": "abreviado_que_no_coincide",
            }
            for item in abreviados
        ),
        *(
            {"old": par["old"], "new": par["new"], "razon": par["estado"]}
            for par in rejected
        ),
    ]

    stamp = _utc_stamp()
    report = _build_report(
        stamp=stamp,
        apply_mode=bool(args.apply),
        git_root=git_root,
        project_root=project_root,
        pair_reports=pair_reports,
        scan_sc=scan_sc,
        scan_non=scan_non,
        remap_counts=remap_counts,
        no_remapeados=no_remapeados,
        orphans=orphans,
        refs=refs,
        saltados=saltados,
    )
    _print_report(report, pair_reports)

    if rejected and not args.skip_rejected:
        print(
            f"[remap] RECHAZADO: {len(rejected)} par(es) no verificable(s) y sin "
            f"--skip-rejected: NO se escribe nada (exit {EXIT_REJECTED}).",
            file=sys.stderr,
        )
        return EXIT_REJECTED

    if args.apply and changes:
        rc = _apply_changes(
            project_root,
            stamp,
            changes,
            originals,
            initial_fingerprints,
            report,
        )
        if rc != EXIT_OK:
            return rc

    for command in _verification_commands(project_root, pair_reports):
        print(f"[remap] verificacion: {command}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
