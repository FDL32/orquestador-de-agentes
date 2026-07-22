#!/usr/bin/env python3
"""Exporta el review packet que YA EXISTE hacia el ensemble (WOT-2026-027p).

REUSO, no reinvencion: el ensamblado del packet vive en
`bus/review_bridge.py::ReviewBridge._build_review_prompt` (la ruta del Manager
por OpenCode lo materializa desde 2026; hay packets reales). Este script lo
CONSUME -- instancia el bridge en modo read-only (EventBus pasivo file-backed,
no emite eventos ni muta colaboracion) y llama al metodo -- y le anade lo que
el ensemble exige y la ruta OpenCode no daba:

  - secciones ``## PROBE`` con ```receipt (command/exit_code[/path]) por cada
    probe que este exportador EJECUTA de verdad al generar, validables con
    `check_bundle_receipts` (rc=0);
  - una seccion ``## UNIVERSE MANIFEST`` con las rutas de
    `review_bundle_contract.compute_code_universe` + sha256 agregado
    ("no recortado" = manifest de RUTAS, no contenidos integros: el CLI de
    026k compara rutas declaradas);
  - cache por clave (ticket_id, motor_head_sha, destino_head_sha,
    sha256(work_plan.md)): invocacion identica -> CACHE_HIT sin regenerar.

Coherencia motor-root (objecion Codex del CF-audit, 2026-07-22): el bridge
resuelve su motor via motor_destination_link.json del workspace; el
``--motor-root`` del CLI gobierna SOLO el universo y los probes. Si ambos
divergen, este script FALLA CERRADO antes de generar (nunca inyecta
motor_root al bridge).

Before: --project-root apunta a un workspace con .agent/collaboration/
    canonico (work_plan/STATE/TURN/execution_log) y
    .agent/config/motor_destination_link.json; --motor-root es el repo git
    del motor (HEAD resoluble). Sin red.
During: verifica coherencia motor-root; computa la clave de cache; en HIT
    imprime CACHE_HIT + ruta y retorna 0 sin regenerar; en MISS instancia
    ReviewBridge read-only, ensambla el prompt canonico, ejecuta los probes
    (universo + frescura de HEAD), compone el packet y lo escribe a
    <workspace>/.agent/runtime/review_packets/ensemble_<ticket>_<clave8>.md.
After: exit 0 con la ruta del packet en stdout; exit !=0 con diagnostico
    self-service (motor divergente, workspace incompleto, git ausente).
    No emite eventos de bus ni toca superficies de colaboracion.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent


def _load_sibling(name: str):
    """Carga un modulo hermano de scripts/ por ruta (patron del repo)."""
    path = _SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise ImportError(f"no se puede cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git_head(repo: Path) -> str:
    """HEAD sha del repo. Propaga CalledProcessError (fail-closed)."""
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return proc.stdout.strip()


def _linked_motor_root(project_root: Path) -> Path | None:
    """Motor declarado por el link del workspace, o None si no hay link."""
    link = project_root / ".agent" / "config" / "motor_destination_link.json"
    try:
        data = json.loads(link.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("motor_root")
    return Path(raw) if raw else None


def compute_cache_key(
    ticket_id: str, motor_head: str, destino_head: str, work_plan_sha: str
) -> str:
    """Clave de cache del contrato: 4 componentes, hex corto estable."""
    blob = f"{ticket_id}\0{motor_head}\0{destino_head}\0{work_plan_sha}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def extract_manifest_paths(packet_text: str) -> set[str]:
    """Rutas declaradas en la seccion ## UNIVERSE MANIFEST del packet.

    Before: `packet_text` es el markdown completo del packet.
    During: localiza la seccion, ignora la linea `sha256:` y las vacias.
    After: retorna el set de rutas (POSIX). Set vacio si no hay seccion --
        el caller decide si eso es recorte (review_bundle_contract lo hara).
    """
    lines = packet_text.splitlines()
    paths: set[str] = set()
    in_section = False
    for line in lines:
        if line.startswith("## "):
            in_section = line.strip() == "## UNIVERSE MANIFEST"
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(("sha256:", "```", "<!--")):
            continue
        paths.add(stripped.replace("\\", "/"))
    return paths


def _build_probe_sections(motor_root: Path, universe: dict, motor_head: str) -> str:
    """Secciones ## PROBE con receipts de los probes REALMENTE ejecutados."""
    n_paths = len(universe["paths"])
    sha12 = universe["sha256"][:12]
    return (
        "## PROBE 1 -- universo mecanico de codigo (git ls-tree + sha256)\n"
        "```receipt\n"
        "command: review_bundle_contract.compute_code_universe(motor_root)\n"
        "exit_code: 0\n"
        "path: scripts/review_bundle_contract.py\n"
        "output: |\n"
        f"  universe_paths={n_paths} sha256={sha12} (agregado sobre HEAD)\n"
        "```\n\n"
        "## PROBE 2 -- frescura del arbol del motor\n"
        "```receipt\n"
        f"command: git -C {motor_root} rev-parse HEAD\n"
        "exit_code: 0\n"
        "output: |\n"
        f"  {motor_head}\n"
        "```\n"
    )


def _build_manifest_section(universe: dict) -> str:
    body = "\n".join(sorted(universe["paths"]))
    return (
        "## UNIVERSE MANIFEST\n"
        "<!-- no-receipt: manifest mecanico, verificable con "
        "review_bundle_contract --bundle-file -->\n"
        f"sha256: {universe['sha256']}\n"
        f"{body}\n"
    )


def export_packet(
    ticket_id: str, motor_root: Path, project_root: Path, *, force: bool = False
) -> tuple[Path, bool]:
    """Genera (o reutiliza) el packet del ensemble para `ticket_id`.

    Before: coherencia motor-root YA verificada por el caller CLI (o el
        caller de biblioteca asume el riesgo); work_plan.md existe.
    During: computa clave; en HIT retorna sin regenerar; en MISS ensambla
        via ReviewBridge (read-only) + probes + manifest y escribe el packet.
    After: retorna (ruta, cache_hit). Propaga OSError/CalledProcessError.
    """
    work_plan = project_root / ".agent" / "collaboration" / "work_plan.md"
    work_plan_sha = hashlib.sha256(work_plan.read_bytes()).hexdigest()
    motor_head = _git_head(motor_root)
    destino_head = _git_head(project_root)
    key = compute_cache_key(ticket_id, motor_head, destino_head, work_plan_sha)

    out_dir = project_root / ".agent" / "runtime" / "review_packets"
    out_dir.mkdir(parents=True, exist_ok=True)
    packet_path = out_dir / f"ensemble_{ticket_id}_{key}.md"
    if packet_path.is_file() and not force:
        return packet_path, True

    # REUSO: bridge read-only (EventBus pasivo file-backed; camino unico
    # confirmado por probe en el CF-audit del contrato, 2026-07-22).
    if str(motor_root) not in sys.path:
        sys.path.insert(0, str(motor_root))
    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    bus = EventBus(project_root / ".agent" / "runtime")
    bridge = ReviewBridge(bus, project_root)
    dtype = "code"
    wp_text = work_plan.read_text(encoding="utf-8")
    for line in wp_text.splitlines():
        if line.lower().startswith("deliverable_type:"):
            dtype = line.split(":", 1)[1].strip() or "code"
            break
    prompt = bridge._build_review_prompt(ticket_id, dtype)

    rbc = _load_sibling("review_bundle_contract")
    universe = rbc.compute_code_universe(motor_root)

    packet = (
        f"# ENSEMBLE REVIEW PACKET -- {ticket_id}\n"
        "<!-- no-receipt: cabecera generada; los claims van en PROBE -->\n"
        f"cache_key: {key}\n"
        f"motor_head: {motor_head}\n"
        f"destino_head: {destino_head}\n\n"
        + _build_probe_sections(motor_root, universe, motor_head)
        + "\n"
        + _build_manifest_section(universe)
        + "\n## CANONICAL REVIEW CONTEXT\n"
        "<!-- no-receipt: ensamblado canonico de ReviewBridge, el mismo que "
        "consume la ruta OpenCode del Manager -->\n\n" + prompt + "\n"
    )
    packet_path.write_text(packet, encoding="utf-8")
    return packet_path, False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Exporta el review packet canonico (ReviewBridge) hacia el "
            "ensemble, con receipts PROBE + manifest de universo + cache."
        )
    )
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--motor-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument(
        "--force", action="store_true", help="Ignora la cache y regenera."
    )
    args = parser.parse_args(argv)

    motor_root = args.motor_root.resolve()
    project_root = args.project_root.resolve()

    # Coherencia motor-root (fail-closed, objecion Codex CF-audit 2026-07-22):
    # el bridge resolvera SU motor por el link del workspace; si difiere del
    # --motor-root del CLI, el universo y la evidencia git hablarian de
    # arboles distintos -> abortar con diagnostico.
    linked = _linked_motor_root(project_root)
    if linked is None:
        print(
            "[export-packet] ERROR: el workspace no declara "
            ".agent/config/motor_destination_link.json (el bridge no podria "
            "resolver el motor para la evidencia git).",
            file=sys.stderr,
        )
        return 2
    if linked.resolve() != motor_root:
        print(
            "[export-packet] ERROR: motor divergente (fail-closed): "
            f"--motor-root={motor_root} pero el link del workspace declara "
            f"{linked.resolve()}. Corrige el flag o el link; nunca se "
            "inyecta motor_root al bridge.",
            file=sys.stderr,
        )
        return 2

    try:
        packet_path, cache_hit = export_packet(
            args.ticket, motor_root, project_root, force=args.force
        )
    except FileNotFoundError as exc:
        print(f"[export-packet] ERROR: artefacto ausente: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"[export-packet] ERROR: git fallo: {exc}", file=sys.stderr)
        return 2

    tag = "CACHE_HIT" if cache_hit else "GENERATED"
    print(f"[export-packet] {tag} {packet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
