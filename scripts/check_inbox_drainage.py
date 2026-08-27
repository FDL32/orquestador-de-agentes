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
    """True solo bajo _archive/backlog_inbox_*/ (subruta explicita, no _archive/**)."""
    parts = rel.parts
    return (
        len(parts) >= 4
        and parts[0] == ".agent"
        and parts[1] == "collaboration"
        and parts[2] == "_archive"
        and parts[3].startswith("backlog_inbox")
    )


def _pending_files(project_root: Path) -> list[Path]:
    canon = canonical_inbox(project_root)
    if not canon.is_dir():
        return []
    return sorted(p for p in canon.glob(TICKET_GLOB) if p.is_file() or p.is_symlink())


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


def _scan_all_tickets(project_root: Path) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Todos los `*.tickets.md` bajo root (prada de caches, sin seguir symlinks).

    Retorna (fichas_reales, problematicas) donde problematicas = (ruta, motivo)
    para symlinks de archivo y rutas cuyo resolve() escapa de project_root; esas
    entradas son strays-unsupported y viajan aparte para el diagnostic.
    """
    found: list[Path] = []
    problems: list[tuple[Path, str]] = []
    root_resolved = project_root.resolve()
    for dirpath, dirnames, filenames in os.walk(project_root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in CACHE_PRUNE_DIRS)
        for fname in sorted(filenames):
            if not fname.endswith(TICKET_SUFFIX):
                continue
            fpath = base / fname
            try:
                rel = fpath.relative_to(project_root)
            except ValueError:  # pragma: no cover - os.walk no lo produce
                continue
            if fpath.is_symlink():
                target = ""
                try:
                    target = str(fpath.resolve())
                except OSError:
                    target = "<unresolvable>"
                problems.append((rel, f"SYMLINK-UNSUPPORTED destino-resuelto={target}"))
                continue
            try:
                resolved = fpath.resolve()
            except OSError as exc:
                problems.append((rel, f"UNRESOLVABLE ({exc})"))
                continue
            if root_resolved not in resolved.parents and resolved != root_resolved:
                problems.append((rel, f"OUTSIDE-ROOT resolve={resolved}"))
                continue
            found.append(rel)
    return found, problems


def classify_inbox(project_root: Path) -> dict:
    """Clasificacion pura del arbol del destino. Read-only.

    Before: project_root Path. During: sin escribeura. After: dict con claves
    pending (lista de{name,age_days}), pending_count, drained_count, strays
    (lista de dicts con path y diagnostic), support (nombres no-ficha del
    canonico y del legacy), canonical_exists.
    """
    canon = canonical_inbox(project_root)
    all_tickets, problems = _scan_all_tickets(project_root)
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
                if p.is_file() and not p.name.endswith(TICKET_SUFFIX)
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


def run_move_strays(project_root: Path) -> int:
    """Reconciliacion mecanica atomica (DoD e + enmienda L711 ALTO)."""
    report = classify_inbox(project_root)
    strays = report["strays"]
    if not strays:
        print(
            f"{_PREFIX} SKIP move-strays: no hay strays que mover (2a pasada = no-op, contadores intactos)."
        )
        return 0
    if any("motivo_extra" in s for s in strays):
        print(
            f"{_PREFIX} ERROR: --move-strays NO mueve symlinks ni rutas fuera de root; trata cada STRAY-UNSUPPORTED a mano con diagnostico:"
        )
        for s in strays:
            if "motivo_extra" in s:
                print(_diagnostic(s, project_root))
        return 1
    # Preflight all-or-nothing: duplicados entre strays o colision con el canonico.
    canon = canonical_inbox(project_root)
    basenames = [s["basename"] for s in strays]
    dups_same_batch = sorted({b for b in basenames if basenames.count(b) > 1})
    existing_conflicts = sorted({b for b in basenames if (canon / b).exists()})
    if dups_same_batch or existing_conflicts:
        print(
            f"{_PREFIX} ERROR abort ATOMICO: lote rechazado ANTES de mover nada (nada movido a medias)."
        )
        for b in dups_same_batch:
            print(f"    duplicado entre strays: {b}")
        for b in existing_conflicts:
            print(f"    colision con el canonico: {canon / b}")
        return 1
    canon.mkdir(parents=True, exist_ok=True)
    moved = 0
    for s in strays:
        src = project_root / s["path"]
        dst = canon / s["basename"]
        if dst.exists():
            print(
                f"{_PREFIX} ERROR abort atomico INESPERADO: {dst} aparecio durante el lote; nada pisado."
            )
            return 1
        shutil.move(str(src), str(dst))
        moved += 1
        print(f"{_PREFIX} MOVED: {s['path']} -> {dst}")
    after = classify_inbox(project_root)
    print(
        f"{_PREFIX} lote completo: {moved} movido(s); strays restantes = {len(after['strays'])}."
    )
    return 0


def run_mark_drained(
    project_root: Path,
    ficha_name: str,
    disposition: str,
    fused_to: str | None,
    reason: str | None,
) -> int:
    if disposition not in {"fused", "moved", "expired"}:
        print(
            f"{_PREFIX} ERROR: --disposition invalida '{disposition}' (enum: fused, moved, expired)."
        )
        return 1
    if disposition == "fused" and not fused_to:
        print(
            f"{_PREFIX} ERROR: disposition=fused exige --fused-to <WOT-id> (evidencia de destino)."
        )
        return 1
    if disposition == "expired" and not reason:
        print(
            f"{_PREFIX} ERROR: disposition=expired exige --reason <motivo> (caducidad con criterio, no por relato)."
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
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
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
