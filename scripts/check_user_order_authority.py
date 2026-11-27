"""Check the canonical user-order authority clause and its citations.

Before: the motor repository contains the protocol, templates, hook, and policy.
During: this guard reads those surfaces and optional live heartbeat state only.
After: exit 0 means every measured authority citation is present; exit 1 names a
contract violation and exit 2 reports an unmeasured environment.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


_role_key_load_error: Exception | None = None
try:
    _role_key_path = (
        Path(__file__).resolve().parent / "flight" / "roster_role_key.py"
    ).resolve()
    _role_key_name = "_flt_roster_role_key_" + str(_role_key_path).replace(
        "\\", "_"
    ).replace(":", "_")
    _role_key_spec = importlib.util.spec_from_file_location(
        _role_key_name, _role_key_path
    )
    if _role_key_spec is None or _role_key_spec.loader is None:
        raise ImportError("no se pudo cargar roster_role_key.py")
    _role_key_module = importlib.util.module_from_spec(_role_key_spec)
    _role_key_spec.loader.exec_module(_role_key_module)
    RosterRoleKeyError = _role_key_module.RosterRoleKeyError
    orchestrator_entry = _role_key_module.orchestrator_entry
except Exception as _role_key_exc:
    _role_key_load_error = _role_key_exc

    class RosterRoleKeyError(ValueError):
        """Fallback resolver error for an isolated FLT copy."""

    def orchestrator_entry(_roles, _error=_role_key_exc):
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MARK = "flight_supervision.md"
R1 = "Una orden posterior y explicita del usuario prevalece sobre una anterior."
R2 = (
    "Un bloqueo por orden del usuario exige antes comprobar los mensajes recientes "
    "del usuario en el hilo de la coordinadora."
)
A = (
    "La orden posterior prevalece en la medida en que contradiga o revoque la anterior; "
    "si no es seguro que la contradiga o revoque, o su alcance, no se levanta el veto, "
    "se comprueba R2, si persiste se pregunta y quedan pendientes solo la accion no "
    "resuelta y sus dependientes, se continua el trabajo independiente. La falta de "
    "respuesta no es autorizacion."
)
B = (
    "un mensaje generico como continua o sigue solo autoriza una accion irreversible o "
    "vetada antes si su contexto establece sin ambiguedad una orden explicita para esa "
    "accion y la revocacion del veto aplicable; si no, procedimiento de duda."
)
SELF_FILES = {
    Path("scripts/check_user_order_authority.py"),
    Path("tests/unit/test_check_user_order_authority.py"),
}


def _read(path: Path) -> tuple[str | None, str | None]:
    """Before: path should be a readable UTF-8 text file. During: read it strictly. After: return text or an error."""
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as exc:
        return None, f"NO MEDIDO: no se pudo leer {path}: {exc}"


def _clause_errors(protocol: str) -> list[str]:
    """Before: protocol is decoded text. During: validate one complete clause. After: return named violations."""
    errors: list[str] = []
    counts = {
        "R1": protocol.count(R1),
        "R2": protocol.count(R2),
        "A": protocol.count(A),
        "B": protocol.count(B),
    }
    for name, count in counts.items():
        if count != 1:
            errors.append(
                f"clausula autoridad: {name} aparece {count} veces; se exige una"
            )
    command = "PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python scripts/flight/user_msgs.py"
    if protocol.count(command) != 1 or "linea final `user msgs: N`" not in protocol:
        errors.append("clausula autoridad: forma de user_msgs.py incompleta")
    if protocol.count("[USUARIO]") < 2 or protocol.count("[DERIVADO") < 6:
        errors.append("clausula autoridad: bloques de procedencia incompletos")
    if (
        protocol.count(
            "confirmado por el usuario, mensaje 661f5a8c-80a5-4274-a626-92ebc5696848"
        )
        < 2
    ):
        errors.append("clausula autoridad: confirmacion de A/B ausente")
    if "PENDIENTE DE CONFIRMACION" in protocol:
        errors.append("clausula autoridad: contiene una etiqueta pendiente")
    return errors


def _hook_errors(root: Path) -> list[str]:
    """Before: the pre-commit file exists. During: inspect the new hook block. After: return wiring violations."""
    path = root / ".pre-commit-config.yaml"
    text, error = _read(path)
    if error:
        return [error]
    if text is None:
        return [f"NO MEDIDO: no se pudo leer {path}"]
    marker = "- id: check-user-order-authority"
    start = text.find(marker)
    if start < 0:
        return ["cableado pre-commit: falta id check-user-order-authority"]
    end = text.find("\n      - id:", start + len(marker))
    block = text[start:] if end < 0 else text[start:end]
    required = (
        "name: check user order authority",
        "entry: uv run python scripts/check_user_order_authority.py",
        "language: system",
        "pass_filenames: false",
        "always_run: true",
        "stages: [pre-commit]",
    )
    return [
        f"cableado pre-commit: falta {item}" for item in required if item not in block
    ]


def _scan_literals(root: Path) -> list[str]:
    """Before: root is a readable repository. During: scan bytes excluding declared self files. After: return duplicate findings."""
    errors: list[str] = []
    literals = (R1, R2, A, B)
    expected = root / "docs/protocol/flight_supervision.md"
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in {".git", ".venv", "sandbox", "__pycache__"}
        ]
        for filename in filenames:
            path = Path(dirpath) / filename
            rel = path.relative_to(root)
            if rel in SELF_FILES:
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                return [f"NO MEDIDO: no se pudo leer {path}: {exc}"]
            for literal in literals:
                count = data.count(literal.encode("utf-8"))
                if path == expected and count != 1:
                    errors.append(
                        f"barrido D-6: {literal[:24]}... aparece {count} veces en el protocolo"
                    )
                elif path != expected and count:
                    errors.append(
                        f"barrido D-6: literal canonico duplicado fuera del protocolo: {path}"
                    )
    return errors


def _workspace_heartbeat(workspace: Path) -> tuple[Path | None, str | None]:
    """Before: workspace is explicitly configured. During: resolve the active roster and supervisor heartbeat. After: return one heartbeat or an environment error."""
    flight_root = workspace / ".agent/runtime/flight"
    if not flight_root.is_dir():
        return None, f"NO MEDIDO: falta el directorio de vuelos en {flight_root}"
    rosters = list(flight_root.rglob("flight_roster.json"))
    if not rosters:
        return None, f"NO MEDIDO: no se encontro flight_roster.json en {flight_root}"
    for roster_path in sorted(
        rosters, key=lambda item: item.stat().st_mtime, reverse=True
    ):
        raw, error = _read(roster_path)
        if error:
            return None, error
        try:
            data = json.loads(raw or "")
            roles = data["active_roles"]
            supervisor = roles["supervisor"]["session_code"]
            coordinator_entry = orchestrator_entry(roles)
            if not isinstance(coordinator_entry, dict):
                raise ValueError("coordinadora ausente en active_roles")
            coordinator = coordinator_entry["session_code"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return None, f"NO MEDIDO: roster roto en {roster_path}: {exc}"
        flight_dir = roster_path.parent
        pattern = f"LATIDO_SUPERVISORA_{supervisor}_sobre_{coordinator}*.md"
        candidates = list((flight_dir / "diseno").glob(pattern))
        if not candidates:
            return None, f"NO MEDIDO: no se encontro latido vivo {pattern}"
        return max(candidates, key=lambda item: item.stat().st_mtime), None
    return None, f"NO MEDIDO: no se pudo resolver roster en {flight_root}"


def check_repository(
    root: Path, latido: Path | None = None, workspace_root: Path | None = None
) -> tuple[int, list[str]]:
    """Before: root points to a motor checkout. During: validate static and live authority surfaces. After: return rc and evidence messages."""
    root = Path(root).resolve()
    static_rc, errors = _static_check(root)
    if static_rc == 2:
        return static_rc, errors
    live_rc, messages = _live_check(latido, workspace_root)
    if live_rc == 2:
        return live_rc, messages
    errors.extend(messages if live_rc == 1 else [])
    if errors:
        return 1, errors
    return 0, messages or ["OK: autoridad de ordenes verificada"]


def _static_check(root: Path) -> tuple[int, list[str]]:
    """Before: root is a motor checkout. During: validate versioned authority surfaces. After: return static rc and findings."""
    protocol, error = _read(root / "docs/protocol/flight_supervision.md")
    if error:
        return 2, [error]
    if protocol is None:
        return 2, ["NO MEDIDO: protocolo no disponible"]
    errors = _clause_errors(protocol)
    for template in (
        root / "prompts/vuelo_pilares_templates/LATIDO_PLANTILLA.md",
        root / "prompts/vuelo_pilares_templates/ARRANQUE_PLANTILLA.md",
    ):
        text, read_error = _read(template)
        if read_error:
            return 2, [read_error]
        if REQUIRED_MARK not in (text or ""):
            errors.append(f"remision: {template} no cita la seccion 2 Autoridad")
    errors.extend(_hook_errors(root))
    policy, policy_error = _read(root / "scripts/guard_denominator_policy.yaml")
    if policy_error:
        return 2, [policy_error]
    if "scripts/check_user_order_authority.py:" not in (
        policy or ""
    ) or "clase: fixed_denominator" not in (policy or ""):
        errors.append("politica de denominador: falta entrada fixed_denominator")
    errors.extend(_scan_literals(root))
    return (1 if errors else 0), errors


def _live_check(
    latido: Path | None, workspace_root: Path | None
) -> tuple[int, list[str]]:
    """Before: optional live-check inputs are resolved. During: inspect explicit or discovered heartbeat. After: return live rc and findings."""
    errors: list[str] = []
    if latido is not None:
        live_path = Path(latido)
        text, read_error = _read(live_path)
        if read_error:
            return 2, [read_error]
        if REQUIRED_MARK not in (text or ""):
            errors.append(f"latido: {live_path} no cita {REQUIRED_MARK}")
    else:
        configured = workspace_root or (
            Path(os.environ["AGENT_PROJECT_ROOT"])
            if os.environ.get("AGENT_PROJECT_ROOT")
            else None
        )
        if configured is None:
            return 0, ["OMISION EXPLICITA: latido vivo NO VERIFICADO sin workspace"]
        else:
            heartbeat, live_error = _workspace_heartbeat(Path(configured))
            if live_error:
                return 2, [live_error]
            text, read_error = _read(heartbeat)
            if read_error:
                return 2, [read_error]
            if REQUIRED_MARK not in (text or ""):
                errors.append(f"latido vivo: {heartbeat} no cita {REQUIRED_MARK}")
    return (1 if errors else 0), errors


def main(argv: list[str] | None = None) -> int:
    """Before: command arguments select optional live checks. During: run the read-only guard. After: print evidence and return its rc."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--latido", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    args = parser.parse_args(argv)
    rc, messages = check_repository(ROOT, args.latido, args.workspace_root)
    for message in messages:
        print(message)
    return rc


if __name__ == "__main__":
    sys.exit(main())
