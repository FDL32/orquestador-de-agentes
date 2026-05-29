#!/usr/bin/env python3
# ruff: noqa: S603, S607
"""
Create semantic checkpoints (M0-M4) for ticket traceability.

Este script crea tags anotadas para los checkpoints semanticos del ciclo de vida
de un ticket. Builder debe crear M3 (review-<ticket>) explicitamente antes de
--mark-ready.

Checkpoints:
- M0: checkpoint/base-<ticket> - Inicio del ticket
- M1: checkpoint/design-<ticket> - Diseño aprobado
- M2: checkpoint/implementation-<ticket> - Implementacion completa
- M3: checkpoint/review-<ticket> - Listo para review (REQUERIDO antes de --mark-ready)
- M4: checkpoint/closed-<ticket> - Ticket cerrado

El comando emite BUILDER_MILESTONE con milestone, tag y SHA verificable.
Si la tag ya existe, hace skip con aviso y no falla.

Uso:
    python scripts/create_checkpoint.py --milestone M3 --ticket-id WP-2026-XXX
    python scripts/create_checkpoint.py --milestone M3 --ticket-id WP-2026-XXX --json
"""

import json
import subprocess
import sys
from pathlib import Path


MILESTONE_TAGS = {
    "M0": "checkpoint/base-{ticket_id}",
    "M1": "checkpoint/design-{ticket_id}",
    "M2": "checkpoint/implementation-{ticket_id}",
    "M3": "checkpoint/review-{ticket_id}",
    "M4": "checkpoint/closed-{ticket_id}",
}

MILESTONE_DESCRIPTIONS = {
    "M0": "Base checkpoint - inicio del ticket",
    "M1": "Design checkpoint - diseño aprobado",
    "M2": "Implementation checkpoint - implementacion completa",
    "M3": "Review checkpoint - listo para review",
    "M4": "Closed checkpoint - ticket cerrado",
}


def get_project_root(args_project_root: str | None) -> Path:
    """Obtener project root desde args o desde el directorio actual."""
    if args_project_root:
        return Path(args_project_root).resolve()
    return Path(__file__).resolve().parent.parent


def tag_exists(project_root: Path, tag_name: str) -> bool:
    """Verificar si una tag ya existe."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", tag_name],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def create_annotated_tag(
    project_root: Path, tag_name: str, message: str
) -> tuple[bool, str]:
    """
    Crear una tag anotada.

    Returns:
        (success, sha_or_error)
    """
    try:
        # Crear tag anotada
        result = subprocess.run(
            ["git", "tag", "-a", tag_name, "-m", message],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()

        # Obtener SHA de la tag
        result = subprocess.run(
            ["git", "rev-parse", tag_name],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "Tag created but could not retrieve SHA"

    except Exception as exc:
        return False, str(exc)


def emit_builder_milestone(
    project_root: Path, milestone: str, tag_name: str, sha: str, ticket_id: str
) -> None:
    """
    Emitir evento BUILDER_MILESTONE al bus de eventos via EventBus.

    Usa EventBus.emit() para que sequence_number sea asignado automaticamente,
    igual que el resto de eventos del bus. Si el bus no esta disponible o no
    puede asignar secuencia, se falla cerrado.
    """
    # Bootstrap sys.path para importar EventBus desde bus/.
    # Usa la ubicacion del script (scripts/), no project_root, porque bus/ vive
    # en el engine root independientemente de donde este el workspace destino.
    _engine_root = str(Path(__file__).resolve().parent.parent)
    if _engine_root not in sys.path:
        sys.path.insert(0, _engine_root)

    payload = {
        "milestone": milestone,
        "tag": tag_name,
        "sha": sha,
        "description": MILESTONE_DESCRIPTIONS.get(milestone, ""),
    }

    try:
        from bus.event_bus import EventBus
    except Exception as exc:
        raise RuntimeError(
            f"Could not import EventBus for BUILDER_MILESTONE: {exc}"
        ) from exc

    runtime_dir = project_root / ".agent" / "runtime"
    bus = EventBus(runtime_dir=runtime_dir / "events")
    record = bus.emit(
        "BUILDER_MILESTONE",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload=payload,
    )
    if record is None:
        raise RuntimeError("BUILDER_MILESTONE could not be emitted via EventBus")


def create_checkpoint(
    project_root: Path, milestone: str, ticket_id: str, json_output: bool
) -> int:
    """
    Crear un checkpoint semantico.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    if milestone not in MILESTONE_TAGS:
        error_msg = f"Invalid milestone '{milestone}'. Must be one of: {', '.join(MILESTONE_TAGS.keys())}"
        if json_output:
            print(
                json.dumps(
                    {"status": "error", "reason": error_msg, "milestone": milestone}
                )
            )
        else:
            print(f"[ERROR] {error_msg}")
        return 1

    tag_name = MILESTONE_TAGS[milestone].format(ticket_id=ticket_id)
    description = MILESTONE_DESCRIPTIONS.get(milestone, "")

    # Verificar si la tag ya existe
    if tag_exists(project_root, tag_name):
        msg = f"Tag {tag_name} already exists; skipping"
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "skipped",
                        "reason": msg,
                        "milestone": milestone,
                        "tag": tag_name,
                        "ticket_id": ticket_id,
                    }
                )
            )
        else:
            print(f"[WARN] {msg}")
        return 0

    # Crear tag anotada
    success, sha_or_error = create_annotated_tag(
        project_root, tag_name, f"{description} - {ticket_id}"
    )

    if not success:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": f"Failed to create tag: {sha_or_error}",
                        "milestone": milestone,
                        "tag": tag_name,
                    }
                )
            )
        else:
            print(f"[ERROR] Failed to create tag {tag_name}: {sha_or_error}")
        return 1

    # Emitir evento BUILDER_MILESTONE; si falla, abortar para no perder trazabilidad.
    try:
        emit_builder_milestone(
            project_root, milestone, tag_name, sha_or_error, ticket_id
        )
    except RuntimeError as exc:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": str(exc),
                        "milestone": milestone,
                        "tag": tag_name,
                    }
                )
            )
        else:
            print(f"[ERROR] {exc}")
        return 1

    if json_output:
        print(
            json.dumps(
                {
                    "status": "created",
                    "milestone": milestone,
                    "tag": tag_name,
                    "sha": sha_or_error,
                    "ticket_id": ticket_id,
                }
            )
        )
    else:
        print(f"[OK] Created {milestone} checkpoint: {tag_name}")
        print(f"     SHA: {sha_or_error}")
        print("     Event: BUILDER_MILESTONE emitted via EventBus")

    return 0


def main() -> int:
    """Punto de entrada principal."""
    import argparse

    parser = argparse.ArgumentParser(description="Create semantic checkpoints")
    parser.add_argument(
        "--milestone",
        type=str,
        required=True,
        choices=["M0", "M1", "M2", "M3", "M4"],
        help="Milestone to create (M0-M4)",
    )
    parser.add_argument(
        "--ticket-id",
        type=str,
        required=True,
        help="Ticket ID (e.g., WP-2026-167)",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args()

    project_root = get_project_root(args.project_root)

    # Verificar que estamos en un repo git
    if not (project_root / ".git").exists():
        error_msg = "Not a git repository"
        if args.json:
            print(json.dumps({"status": "error", "reason": error_msg}))
        else:
            print(f"[ERROR] {error_msg}")
        return 1

    return create_checkpoint(project_root, args.milestone, args.ticket_id, args.json)


if __name__ == "__main__":
    sys.exit(main())
