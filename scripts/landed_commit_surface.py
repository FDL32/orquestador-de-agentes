# ruff: noqa: S603,S607
"""WOT-2026-062a: public auditable surface por landed-commits, fuera del motor.

``_ticket_landed_by_archived_commit`` (``.agent/agent_controller.py``)
resuelve la raiz POR ORIGEN de la fila (WOT-2026-054e), pero es privada
y su modulo no es paquete Python: un acreditador externo no puede invocarla
y su sonda replica la logica a mano, midiendo otra cosa. Este modulo expone
esa logica como superficie PUBLICA con raices INYECTADAS, de modo que un
acreditador externo pase las suyas sin depender de la resolucion interna del motor.

La privada queda INTACTA (alternativa aceptable del contrato, seccion STOP):
delegar romperia el seam documentado de 024q (get_collab_dir() con un objeto
no-filesystem, _FakeCollab, que engancha la lectura del archive a un read_text
inyectado), porque la superficie publica construye el archive desde project_root
inyectado, un Path real, y no puede recibir ese objeto sin romper la firma
congelada. La equivalencia entre ambas puertas la cubre
test_public_surface_agrees_with_private_impl.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def ticket_landed_by_archived_commit(
    plan_id: str,
    *,
    motor_root: Path,
    project_root: Path,
    ref: str = "origin/main",
) -> bool:
    """True sii la fila archivada del ticket cita un commit que aterrizo.


    Superficie PUBLICA y auditable desde fuera del motor (WOT-2026-062a).
    Las raices se INYECTAN: un acreditador externo pasa las suyas y no depende
    de la resolucion interna del motor.


    Before: plan_id non-empty; motor_root y project_root roots git reales.

        Lee el archive bajo project_root y corre git read-only; nunca muta.
    During: parsa el archive, filtra a este ticket's (id, sha) pairs,
        los agrupa por el home root que realmente tiene su objeto( motor primero,
        orden historico),, y clasifica cada grupo contra ref en ese home.


    After: devuelve True sii el ticket tiene al menos un par citado y TODOS


        ellos aterrizan como OK u OK_BY_SUBJECT ( un commit agrupado debe


        aterrizar entero); False en cualquier error de lectura/parseo/git


        (fail-closed: no probado).


    """
    try:
        from scripts.check_backlog_commits_landed import audit, parse_archived_commits

        collab_dir = project_root / ".agent" / "collaboration"
        archive = collab_dir / "_archive" / "backlog_done.md"
        content = archive.read_text(encoding="utf-8-sig")
        pairs = [
            (tid, sha) for tid, sha in parse_archived_commits(content) if tid == plan_id
        ]
        if not pairs:
            return False

        archive_home = project_root
        motor_home: Path | None = None
        candidate = motor_root.resolve()
        if archive_home is None or candidate != archive_home:
            motor_home = candidate

        by_home: dict[Path, list[tuple[str, str]]] = {}
        for pair in pairs:
            home = _pair_home_root(pair[1], archive_home, motor_home)
            by_home.setdefault(home, []).append(pair)

        results: list[dict] = []
        for home, home_pairs in by_home.items():
            siblings = [r for r in (motor_home, archive_home) if r != home]
            sibling = siblings[0] if siblings else None
            results.extend(audit(home_pairs, ref, home, other_repo=sibling))

        return bool(results) and all(
            r["verdict"] in ("OK", "OK_BY_SUBJECT") for r in results
        )
    except Exception:
        return False


def _pair_home_root(
    sha: str,
    archive_home: Path | None,
    extra_home: Path | None,
) -> Path | None:
    """Pick the git root que realmente tiene el objeto de un par (ticket, sha).



    WOT-2026-062a: helper local de la superficie publica, misma logica que
    _pair_home_root de agent_controller.py (WOT-2026-054e). La equivalencia
    entre ambas la cubre el test de acuerdo; que deriven es exactamente lo que


    ese test debe cazar.



    Before: sha cualquier token; archive_home el root del archive (None cuando
        el llamante no pudo derivar uno); extra_home el repo hermano de la
        topologia o None. During: un git cat-file -e sha acentuado commit read-only
        por root candidato( motor primero, reflejando el orden historico).
    After: devuelve el primer root que tiene el commit; cuando NINGUN root lo




        tiene, devuelve el hermano motor si lo hay, sino archive_home -- asi el guard
        de landing sigue emitiendo su WARN de diseno (con other_repo como testigo
        del hermano), nunca un ERROR espurio.


    """
    candidates = [c for c in (extra_home, archive_home) if isinstance(c, Path)]
    try:
        for root in candidates:
            if _root_has_commit_object(root, sha):
                return root
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return (
        candidates[0]
        if candidates
        else (extra_home if extra_home is not None else archive_home)
    )


def _root_has_commit_object(root: Path, sha: str) -> bool:
    """True si root resuelve sha a un objeto commit ( git read-only).



    WOT-2026-062a: helper local de la superficie publica, mismo seam que
    _root_has_commit_object de agent_controller.py (WOT-2026-054e): el probe
    de existencia corre SOLO en la frontera de eleccion de root; los veredictos


    de landing siguen siendo propiedad de check_backlog_commits_landed (este


    modulo nunca los reinterpreta).


    """
    try:
        proc = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=str(root),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0
