#!/usr/bin/env python3
"""Guard: un solo backlog_inbox canonico, descubierto desde CODIGO (WOT-2026-042u).

El fallo del ticket: "hay DOS buzones de fichas y el drenaje no lee ninguno".
El consumidor de la fusion (Bloque 8.bis) era 100% prompt-level -- una NORMA.
Este modulo es la BARRERA: declara la ruta canonica en codigo, descubre el arbol
del destino y hace que una ficha fuera de canonico FALLA EXPLICITAMENTE con
diagnostico self-service, en vez de quedar invisible.

Tricotomia (DoD a, enmienda CONTRACT_AUDIT L710/L711 BA05 absorbida):
  pending  -- `*.tickets.md` HIJO DIRECTO del canonico.
  drained  -- canonico/_drained/** y `.agent/collaboration/_archive/backlog_inbox_*/**`
              (subruta EXPLICITA de archivo terminal de buzones, patron medido
              `backlog_inbox_fusionado_20260811/`). El archivo ajeno a ese patron
              NO esta exento: si hay una ficha ahi, es stray.
  stray    -- el resto de `*.tickets.md` bajo --project-root. Se prunan SOLO caches
              de codigo; `.agent/runtime/**` NO se pruna (reabria la invisibilidad).
              Symlinks/junctions: followlinks=False; un archivo symlink cuenta como
              STRAY-UNSUPPORTED con su destino resuelto; containment: toda ruta
              resuelta debe quedar bajo project_root o es STRAY-OUTSIDE-ROOT.

Asimetria deliberate (DoD c + contrato del README del buzon):
  stray    -> exit 1 BLOQUEANTE, con las TRES partes por ficha: (i) que fichero,
              (ii) donde deberia estar, (iii) como moverlo, + comando de re-check.
  pending  -> WARN census (n + edad de la mas antigua), exit 0: "registrar nunca
              debe bloquear el cierre que lo permite".
  vacio    -> SKIP nombrado explicito ("No es un PASS"), exit 0.

Operaciones declarativas con dientes propios (no un second descubridor):
  --move-strays   reconciliacion mecanica, ATOMICA all-or-nothing: preflight de
                  basenames (dup entre strays o contra canonico) aborta el lote
                  COMPLETO antes de mover nada; nunca pisa un fichero existente.
  --mark-drained  borra-o-marca (DoD d): MUEVE la ficha pending a
                  canonical/_drained/YYYY-MM/ y anade una linea a drain_ledger.jsonl.
                  Segunda pasada = no-op VERIFICABLE por conteos de artefactos
                  ("already drained (ledger hit)"), no por exit code.

Before:  `--project-root <destino>` (ARGUMENTO OBLIGATORIO: el guard NO resuelve la
         topologia por su cuenta -- stop heredado del contrato 042x). El canonico
         puede existir o no; las operaciones sobre fichas exigen que exista.
During:  auditoria = read-only puro sobre el filesystem. Las dos operaciones son la
         unica rama que escribe (shutil.move y append al ledger); ninguna toca git,
         backlog.md ni la red.
After:   exit 0 sin strays (pending sale como WARN census nombrado); exit 1 con
         estrays detallados, o con operacion rechazada (colision/dup/ledger mismatch);
         exit 2 = uso (argparse). --json emite los conteos como artefacto leible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# DoD (a): el canonico se declara AQUI, en codigo, no en prosa de prompt.
CANONICAL_INBOX_REL = Path(".agent") / "collaboration" / "backlog_inbox"

TICKET_GLOB = "*.tickets.md"
DRAINED_DIRNAME = "_drained"
LEDGER_NAME = "drain_ledger.jsonl"
TICKET_SUFFIX = ".tickets.md"
LEGACY_INBOX_REL = Path("orchestrator_pipeline") / "backlog_inbox"

# Solo caches de codigo: ninguna zona de estado operativo entra en el prune.
CACHE_PRUNE_DIRS = frozenset(
    {
        ".venv",
        "venv",
        ".git",
        "__pycache__",
        "node_modules",
        ".uv-cache",
        "uv-cache",
        "dist",
        "build",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)

_PREFIX = "[inbox-drainage]"

# Forma de id canonico de ticket (0.d de orchestrator_pipeline.md + validador del
# bus `(?:WP|WT|[A-Z]{3})-\d{4}-...`): prefijo 2-3 mayusculas, ano, numero y sufijo
# de subfase opcional. Solo se exige para --fused-to (trazabilidad del ledger).
_FUSED_TO_RE = re.compile(r"[A-Z]{2,3}-\d{4}-\d{1,3}[A-Za-z]?")


def _dir_is_untraversed_link(dpath: Path) -> bool:
    """True si os.walk(followlinks=False) NO va a recorrer este subdirectorio.

    Un symlink de archivo lo delata `is_symlink()`; en Python >=3.12 tambien
    junctiones (que 3.10 recorre). La funcion propia permite fijar la rama en
    tests con monkeypatch cuando el SO no deja crear enlaces reales
    (Windows sin privilegios) -- la barrera es alcanzable, no decorativa.
    """
    if dpath.is_symlink():
        return True
    is_junction = getattr(dpath, "is_junction", None)
    try:
        return bool(is_junction and is_junction())
    except OSError:
        return False


def canonical_inbox(project_root: Path) -> Path:
    """Ruta canonica del buzon, resuelta contra el project_root dado."""
    return project_root / CANONICAL_INBOX_REL


def _drained_zone(project_root: Path) -> Path:
    return canonical_inbox(project_root) / DRAINED_DIRNAME


def _ledger_path(project_root: Path) -> Path:
    return _drained_zone(project_root) / LEDGER_NAME


def _archive_exempt_dir(project_root: Path) -> Path:
    return project_root / ".agent" / "collaboration" / "_archive"


def _is_in_archive_exempt_prefix(rel: Path) -> bool:
    """True solo bajo _archive/backlog_inbox_*/ (subruta explicita, no _archive/**).

    WOT-2026-042u (nit MANAGER_REVIEW L700): el predicado usaba
    `startswith("backlog_inbox")`, que exenta ADEMAS cualquier directorio que
    meramente EMPIECE por esa cadena (`backlog_inboxes_falso/`, `backlog_inboxXYZ/`)
    -- contradiciendo este mismo docstring, que promete patron EXPLICITO, y el del
    modulo: "El archivo ajeno a ese patron NO esta exento: si hay una ficha ahi, es
    stray". Una exencion mas ancha que su contrato convierte fichas stray en
    `drained` SILENCIOSAMENTE, que es la clase de invisibilidad que este guard
    cierra. El patron correcto es el nombre exacto o el prefijo CON separador.
    """
    parts = rel.parts
    return (
        len(parts) >= 4
        and parts[0] == ".agent"
        and parts[1] == "collaboration"
        and parts[2] == "_archive"
        and (parts[3] == "backlog_inbox" or parts[3].startswith("backlog_inbox_"))
    )


def _is_ticket_name(name: str) -> bool:
    """Poblacion de fichas: `*.tickets.md` SIN importar el caso de la extension.

    La regla del vecino 6n (check_dec_receipt) usa glob de pathlib, que en
    Windows normaliza caso: una `FP-X.TICKETS.MD` es ficha PARA EL y no lo seria
    para un `endswith` stricto == la misma enfermedad del ticket (dos consumidores
    del buzon, miradas distintas). Aqui se iguala hacia MAS estricto (casefold
    en ambos SO): nada con forma de ficha queda fuera de la tricotomia.
    """
    return name.lower().endswith(TICKET_SUFFIX)


def _pending_files(project_root: Path) -> list[Path]:
    canon = canonical_inbox(project_root)
    if not canon.is_dir():
        return []
    return sorted(
        p
        for p in canon.iterdir()
        if p.is_file() or p.is_symlink()
        if _is_ticket_name(p.name)
    )


def _ledger_names(project_root: Path) -> set[str]:
    ledger = _ledger_path(project_root)
    names: set[str] = set()
    if not ledger.is_file():
        return names
    for raw in ledger.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("ficha"):
            names.add(str(rec["ficha"]))
    return names


def _dirlink_note(dpath: Path, project_root: Path) -> tuple[Path, str]:
    """Nota (rel, motivo) de un dir-symlink no recorrido, con destino resuelto."""
    try:
        rel_d = dpath.relative_to(project_root)
    except ValueError:  # pragma: no cover - os.walk no lo produce
        rel_d = Path(str(dpath))
    try:
        target = str(dpath.resolve())
    except OSError:
        target = "<unresolvable>"
    return (rel_d, f"DIR-SYMLINK no recorrido destino-resuelto={target}")


def _ticket_entry(
    fpath: Path, project_root: Path, root_resolved: Path
) -> tuple[str, object]:
    """Clasifica UN archivo candidato: ('found', rel) | ('problem', (rel, motivo)).

    Un symlink de archivo jamas es pending silencioso; una ruta cuyo resolve()
    escapa del proyecto tampoco (enmiendas L710/L711). Nunca lanza: devuelve la
    clase para que el caller la enrumbe.
    """
    try:
        rel = fpath.relative_to(project_root)
    except ValueError:  # pragma: no cover - os.walk no lo produce
        return ("skip", None)
    if fpath.is_symlink():
        try:
            target = str(fpath.resolve())
        except OSError:
            target = "<unresolvable>"
        return ("problem", (rel, f"SYMLINK-UNSUPPORTED destino-resuelto={target}"))
    try:
        resolved = fpath.resolve()
    except OSError as exc:
        return ("problem", (rel, f"UNRESOLVABLE ({exc})"))
    if root_resolved not in resolved.parents and resolved != root_resolved:
        return ("problem", (rel, f"OUTSIDE-ROOT resolve={resolved}"))
    return ("found", rel)


def _scan_all_tickets(
    project_root: Path,
) -> tuple[list[Path], list[tuple[Path, str]], list[tuple[Path, str]]]:
    """Todos los `*.tickets.md` bajo root, sin seguir enlaces.

    Retorna (fichas_reales, problematicas, dir_links). `problematicas` son
    symlinks de archivo / rutas que escapan del root (strays-unsupported);
    `dir_links` son subdirectorios-enlace que followlinks=False NO recorre --
    posibles escondites, reportados loud (enmienda MANAGER_REVIEW BA10 deepseek
    2026-08-27) y jamsa seguidos (ciclos). Los CACHE_PRUNE_DIRS se excluyen del
    recorrido igual que antes (test_cache_dirs_pruned fija esa arista).
    """
    found: list[Path] = []
    problems: list[tuple[Path, str]] = []
    dir_links: list[tuple[Path, str]] = []
    root_resolved = project_root.resolve()

    for dirpath, dirnames, filenames in os.walk(project_root, followlinks=False):
        base = Path(dirpath)
        surviving = []
        for d in sorted(dirnames):
            dpath = base / d
            if d in CACHE_PRUNE_DIRS:
                continue  # cache de codigo: ni se recorre ni se reporta
            if _dir_is_untraversed_link(dpath):
                # una ficha detras seria INVISIBLE: nombrar, no seguir
                dir_links.append(_dirlink_note(dpath, project_root))
                continue
            surviving.append(d)
        dirnames[:] = surviving
        for fname in sorted(filenames):
            if not _is_ticket_name(fname):
                continue
            kind, payload = _ticket_entry(base / fname, project_root, root_resolved)
            if kind == "found":
                found.append(payload)
            elif kind == "problem":
                problems.append(payload)
    return found, problems, dir_links


def classify_inbox(project_root: Path) -> dict:
    """Clasificacion pura del arbol del destino. Read-only.

    Before: project_root Path. During: sin escribeura. After: dict con claves
    pending (lista de{name,age_days}), pending_count, drained_count, strays
    (lista de dicts con path y diagnostic), support (nombres no-ficha del
    canonico y del legacy), canonical_exists.
    """
    canon = canonical_inbox(project_root)
    all_tickets, problems, dir_links = _scan_all_tickets(project_root)
    now = datetime.now(timezone.utc)

    pending: list[dict] = []
    drained_count = 0
    strays: list[dict] = []

    canon_rel = canon.relative_to(project_root)
    drained_rel_prefix = canon_rel / DRAINED_DIRNAME
    for rel in all_tickets:
        if rel.parent == canon_rel:
            st = (project_root / rel).stat()
            age_days = max(
                0, (now - datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)).days
            )
            pending.append({"name": rel.name, "age_days": age_days})
        elif (
            rel == drained_rel_prefix
            or str(rel).startswith(str(drained_rel_prefix) + os.sep)
            or _is_in_archive_exempt_prefix(rel)
        ):
            drained_count += 1
        else:
            strays.append({"path": str(rel), "basename": rel.name})

    for rel, motivo in problems:
        strays.append({"path": str(rel), "basename": rel.name, "motivo_extra": motivo})

    support: list[str] = []
    if canon.is_dir():
        support.extend(
            sorted(
                p.name
                for p in canon.iterdir()
                if p.is_file() and not _is_ticket_name(p.name)
            )
        )
    legacy = project_root / LEGACY_INBOX_REL
    legacy_files = []
    if legacy.is_dir():
        legacy_files = sorted(p.name for p in legacy.iterdir() if p.is_file())

    return {
        "canonical_exists": canon.is_dir(),
        "pending": sorted(pending, key=lambda p: -p["age_days"]),
        "pending_count": len(pending),
        "drained_count": drained_count,
        "strays": strays,
        "dir_links": [{"path": str(p), "motivo": m} for p, m in dir_links],
        "legacy_inbox_files": legacy_files,
        "support_files_canonical": support,
    }


def _diagnostic(stray: dict, project_root: Path) -> str:
    canon = canonical_inbox(project_root)
    lines = [
        f"  STRAY: {stray['path']}"
        + (f"  [{stray['motivo_extra']}]" if stray.get("motivo_extra") else ""),
        f"    donde deberia estar: {canon / stray['basename']}",
        f"    como moverlo:      mv '{project_root / stray['path']}' '{canon}/'   "
        "(o: python scripts/check_inbox_drainage.py --project-root "
        f"'{project_root}' --move-strays  # atomico, no pisa colisiones)",
    ]
    return "\n".join(lines)


def _census_lines(report: dict) -> list[str]:
    lines = []
    if report["pending_count"]:
        oldest = report["pending"][0]
        lines.append(
            f"{_PREFIX} WARN census: {report['pending_count']} fichas pendientes de fusion "
            f"(mas antigua: {oldest['name']} -- {oldest['age_days']} dias). "
            "Fusion = Bloque 8.bis + `--mark-drained` (esta misma puerta). El WARN NUNCA bloquea: "
            "registrar no puede bloquear el cierre que lo permite."
        )
    else:
        lines.append(
            f"{_PREFIX} SKIP: 0 fichas pendientes en el canonico. No es un PASS de fusion: no hay nada que fusionar."
        )
    if report["drained_count"]:
        lines.append(
            f"{_PREFIX} INFO drained: {report['drained_count']} fichas en zonas terminales (_drained/ o _archive/backlog_inbox_*)."
        )
    if report["support_files_canonical"]:
        lines.append(
            f"{_PREFIX} INFO material de apoyo (no-fichas, 4 clases declaradas por la ficha AMPLIADA, no renombrar): "
            + ", ".join(report["support_files_canonical"])
        )
    if report["legacy_inbox_files"]:
        lines.append(
            f"{_PREFIX} INFO legacy buzon de fichas no-canonico 'orchestrator_pipeline/backlog_inbox/' con {len(report['legacy_inbox_files'])} archivo(s): "
            + ", ".join(report["legacy_inbox_files"])
        )
    lines.extend(
        f"{_PREFIX} WARN dir-symlink no recorrido (posible escondite; enmienda "
        f"MANAGER_REVIEW, sin seguir para evitar ciclos): {dl['path']} :: {dl['motivo']}. "
        "Reconcilia: sustituye el enlace por archivos reales (o mueve lo que esconda "
        "al canonico) y elimina el enlace."
        for dl in report.get("dir_links", [])
    )
    return lines


def run_audit(project_root: Path, as_json: bool = False) -> int:
    report = classify_inbox(project_root)
    human_stream = sys.stderr if as_json else sys.stdout
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    for line in _census_lines(report):
        print(line, file=human_stream)
    if report["strays"]:
        print(
            f"{_PREFIX} ERROR: {len(report['strays'])} ficha(s) FUERA del buzon canonico. Diagnostico self-service:",
            file=human_stream,
        )
        for stray in report["strays"]:
            print(_diagnostic(stray, project_root), file=human_stream)
        print(
            f"{_PREFIX} re-verificar: python scripts/check_inbox_drainage.py "
            f"--project-root '{project_root}'   (0 errores = sin estrays)",
            file=human_stream,
        )
        return 1
    if not as_json:
        print(f"{_PREFIX} OK: sin estrays fuera del canonico.")
    return 0


def _rollback_moves(moved: list[tuple[Path, Path]]) -> tuple[int, list[str]]:
    """Revierte (src,dst) en orden inverso. Devuelve (n_reverted, fallos)."""
    reverted: list[str] = []
    failed: list[str] = []
    for src, dst in reversed(moved):
        try:
            shutil.move(str(dst), str(src))
            reverted.append(str(src))
        except OSError as exc:  # noqa: PERF203 - cada revertida necesita su propio veredicto; son lotes pequenos
            failed.append(f"{dst} -> {src} ({exc})")
    return len(reverted), failed


def _reject_unsupported_strays(strays: list[dict], project_root: Path) -> bool:
    """Si algun stray es symlink/escape, lo nombra y devuelve True (no se mueve)."""
    bad = [s for s in strays if "motivo_extra" in s]
    if not bad:
        return False
    print(
        f"{_PREFIX} ERROR: --move-strays NO mueve symlinks ni rutas fuera de root; trata cada STRAY-UNSUPPORTED a mano con diagnostico:"
    )
    for s in bad:
        print(_diagnostic(s, project_root))
    return True


def _preflight_conflicts(strays: list[dict], canon: Path) -> list[str]:
    """Mensajes de bloqueo del lote (dups entre strays o colision con el canonico)."""
    basenames = [s["basename"] for s in strays]
    msgs = [
        f"    duplicado entre strays: {b}"
        for b in sorted({b for b in basenames if basenames.count(b) > 1})
    ]
    msgs += [
        f"    colision con el canonico: {canon / b}"
        for b in sorted({b for b in basenames if (canon / b).exists()})
    ]
    return msgs


def run_move_strays(project_root: Path) -> int:
    """Reconciliacion mecanica atomica (DoD e + enmienda L711 ALTO + L701 ALTO)."""
    report = classify_inbox(project_root)
    strays = report["strays"]
    if not strays:
        print(
            f"{_PREFIX} SKIP move-strays: no hay strays que mover (2a pasada = no-op, contadores intactos)."
        )
        return 0
    if _reject_unsupported_strays(strays, project_root):
        return 1
    canon = canonical_inbox(project_root)
    conflicts = _preflight_conflicts(strays, canon)
    if conflicts:
        print(
            f"{_PREFIX} ERROR abort ATOMICO: lote rechazado ANTES de mover nada (nada movido a medias)."
        )
        for b in conflicts:
            print(b)
        return 1
    canon.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []  # (src, dst) en orden de ejecucion
    try:
        for s in strays:
            src = project_root / s["path"]
            dst = canon / s["basename"]
            if dst.exists():
                raise OSError(f"{dst} aparecio durante el lote")
            shutil.move(str(src), str(dst))
            moved.append((src, dst))
            print(f"{_PREFIX} MOVED: {s['path']} -> {dst}")
    except OSError as exc:
        # atomicidad REAL del lote (enmienda MANAGER_REVIEW BA05 ALTO
        # 2026-08-27): un fallo a mitad revierte en orden inverso; lo ya movido
        # vuelve a su sitio, el lote no termina "a medias".
        done, failed = _rollback_moves(moved)
        print(
            f"{_PREFIX} ERROR abort ATOMICO por fallo a mitad: {exc}; rollback inverso "
            f"{done}/{len(moved)} restaurado(s)."
        )
        for fpath in failed:
            print(f"{_PREFIX} ERROR ROLLBACK-FALLO requiere auditoria manual: {fpath}")
        return 1
    after = classify_inbox(project_root)
    print(
        f"{_PREFIX} lote completo: {len(moved)} movido(s); strays restantes = {len(after['strays'])}."
    )
    return 0


def _fused_to_resolves(project_root: Path, fused_to: str) -> bool:
    """El id `fused` debe ser RESOLUBLE en el registro del propio destino: fila en
    `backlog.md` (cola viva) o en `_archive/backlog_done.md` (traspaso).

    Mecanico, no semantico (la comprobacion de fused es NON-GOAL de la ficha): esto
    es existencia del id-destino, no juicio sobre el contenido. (enmienda
    MANAGER_REVIEW BA05 MEDIO L702 2026-08-27)
    """
    needles = (
        project_root / ".agent/collaboration/backlog.md",
        project_root / ".agent/collaboration/_archive/backlog_done.md",
    )
    for fpath in needles:
        try:
            text = fpath.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if fused_to in text:
            return True
    return False


def _validate_mark_drained_args(
    disposition: str,
    fused_to: str | None,
    reason: str | None,
) -> str | None:
    """None si validos; mensaje de ERROR en contrario (rama separada del I/O)."""
    if disposition not in {"fused", "moved", "expired"}:
        return f"{_PREFIX} ERROR: --disposition invalida '{disposition}' (enum: fused, moved, expired)."
    if disposition == "fused" and not fused_to:
        return f"{_PREFIX} ERROR: disposition=fused exige --fused-to <WOT-id> (evidencia de destino)."
    if disposition == "fused" and not _FUSED_TO_RE.fullmatch(str(fused_to)):
        return (
            f"{_PREFIX} ERROR: --fused-to='{fused_to}' no tiene forma de id canonico "
            "<PREFIJO>-YYYY-NNNx (p. ej. WOT-2026-042u). El ledger es trazabilidad, "
            "no prosa libre (enmienda MANAGER_REVIEW BA05 MEDIO 2026-08-27; formato "
            "gobernado por '0.d' de orchestrator_pipeline.md y el validador del bus)."
        )
    if disposition == "expired" and not reason:
        return f"{_PREFIX} ERROR: disposition=expired exige --reason <motivo> (caducidad con criterio, no por relato)."
    return None


def run_mark_drained(
    project_root: Path,
    ficha_name: str,
    disposition: str,
    fused_to: str | None,
    reason: str | None,
) -> int:
    err = _validate_mark_drained_args(disposition, fused_to, reason)
    if err:
        print(err)
        return 1
    if disposition == "fused" and not _fused_to_resolves(project_root, str(fused_to)):
        print(
            f"{_PREFIX} ERROR: --fused-to='{fused_to}' no resuelve en el registro del "
            "destino (.agent/collaboration/backlog.md ni _archive/backlog_done.md). "
            "Orden correcto (8.bis): escribir PRIMERO la fila destino, luego drenar "
            "la ficha. Si la fila es nueva de este ciclo, ya debe estar en backlog.md."
        )
        return 1
    canon = canonical_inbox(project_root)
    ficha = canon / ficha_name
    ledger = _ledger_path(project_root)
    if ficha_name in _ledger_names(project_root):
        if not ficha.exists():
            print(
                f"{_PREFIX} already drained (ledger hit): {ficha_name} -- 2a pasada no-op, artefactos intactos."
            )
            return 0
        print(
            f"{_PREFIX} ERROR estado dividido: {ficha_name} figura en el ledger PERO sigue en el canonico; no se toca nada, audita a mano."
        )
        return 1
    if ficha.is_symlink():
        print(
            f"{_PREFIX} ERROR: '{ficha_name}' es un SYMLINK (el censo lo trata como stray-unsupported); no se drena por el cano: reconcilia primero su destino real."
        )
        return 1
    if not ficha.is_file():
        pending = [p.name for p in _pending_files(project_root)]
        print(
            f"{_PREFIX} ERROR: '{ficha_name}' no es una ficha pending del canonico. pending = {pending if pending else '(vacio)'}"
        )
        print(
            f"{_PREFIX} re-verificar: python scripts/check_inbox_drainage.py --project-root '{project_root}' --json"
        )
        return 1
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    dest_dir = _drained_zone(project_root) / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ficha_name
    if dest.exists():
        print(
            f"{_PREFIX} ERROR: {dest} ya existe sin entrada de ledger coherente: no se pisa nada, audita a mano."
        )
        return 1
    shutil.move(str(ficha), str(dest))
    record = {
        "ficha": ficha_name,
        "disposition": disposition,
        "fused_to": fused_to,
        "reason": reason,
        "drained_at": datetime.now(timezone.utc).isoformat(),
        "month": month,
    }
    try:
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Atomicidad move+ledger (enmienda MANAGER_REVIEW BA05 MEDIO
        # 2026-08-27): sin linea en el ledger, un archivo ya movido es estado
        # dividido; se revierte el move y nada queda drenado a medias.
        try:
            shutil.move(str(dest), str(ficha))
            print(
                f"{_PREFIX} ERROR ledger no escribible ({exc}); move revertido -- nada drenado."
            )
        except OSError as exc2:
            print(
                f"{_PREFIX} ERROR ledger fallo Y el revert fallo ({exc} / {exc2}): {dest} exige auditoria manual."
            )
        return 1
    print(f"{_PREFIX} DRAINED: {ficha_name} -> {dest} (ledger +1 linea)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="DoD en el work_plan de WOT-2026-042u; contrato del buzon: su README y el Bloque 8.bis.",
    )
    parser.add_argument(
        "--project-root",
        required=True,
        type=Path,
        help="Raiz del repo_destino (ARGUMENTO, nunca env).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Volcar la clasificacion como JSON (artefacto de evidencia).",
    )
    parser.add_argument(
        "--move-strays",
        action="store_true",
        help="Reconciliacion mecanica atomica al canonico.",
    )
    parser.add_argument(
        "--mark-drained",
        metavar="FICHA",
        help="Nombre de ficha pending del canonico a drenar (se MUEVE a _drained/YYYY-MM/ y se registra en el ledger).",
    )
    parser.add_argument(
        "--disposition", choices=("fused", "moved", "expired"), default=None
    )
    parser.add_argument(
        "--fused-to",
        default=None,
        help="WOT-id destino (obligatorio con --disposition fused).",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Motivo (obligatorio con --disposition expired; opcional en el resto).",
    )
    args = parser.parse_args(argv)

    if args.mark_drained and args.move_strays:
        parser.error(
            "--move-strays y --mark-drained son excluyentes (un lote por invocacion, fallo 2026-08-27)"
        )

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        print(f"{_PREFIX} ERROR: project-root no es un directorio: {project_root}")
        return 1
    if args.mark_drained:
        return run_mark_drained(
            project_root,
            args.mark_drained,
            args.disposition or "",
            args.fused_to,
            args.reason,
        )
    if args.move_strays:
        return run_move_strays(project_root)
    return run_audit(project_root, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
