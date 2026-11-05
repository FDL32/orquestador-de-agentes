"""Start review lenses for one ticket from explicit, portable inputs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any


Runner = Callable[..., subprocess.CompletedProcess[str]]


class StartError(ValueError):
    """A fail-closed start contract failure."""


def _run(runner: Runner, command: Sequence[str], *, cwd: Path | None = None):
    """Run one argv-only subprocess with an explicit cwd."""
    return runner(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )


def _git(runner: Runner, repo: Path, *args: str):
    """Run git against one explicit repository."""
    return _run(runner, ["git", "-C", str(repo), *args])


def _path(raw: str, *, directory: bool = False) -> Path:
    """Resolve and validate one explicit path."""
    if not str(raw).strip():
        raise StartError("ruta obligatoria ausente")
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise StartError(f"ruta inexistente: {raw}")
    if directory and not path.is_dir():
        raise StartError(f"no es directorio: {path}")
    if not directory and not path.is_file():
        raise StartError(f"no es fichero: {path}")
    return path


def _commit(runner: Runner, repo: Path, ref: str) -> str:
    """Resolve one commit reference."""
    result = _git(runner, repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    value = result.stdout.strip()
    if result.returncode or len(value) != 40:
        raise StartError(f"ref invalida: {ref}")
    return value


def _clone_at_tip(runner: Runner, source: Path, clone: Path, tip: str) -> None:
    """Create an exact-tip clone and reject a discrepant HEAD."""
    if clone.exists():
        if not clone.is_dir():
            raise StartError(f"clon no es directorio: {clone}")
        result = _git(runner, clone, "fetch", str(source))
        if result.returncode:
            raise StartError("fetch del clon fallido")
    else:
        clone.parent.mkdir(parents=True, exist_ok=True)
        result = _run(
            runner, ["git", "clone", "--no-hardlinks", str(source), str(clone)]
        )
        if result.returncode:
            raise StartError("clone fallido")
    result = _git(runner, clone, "checkout", "--detach", tip)
    if result.returncode:
        raise StartError("checkout del clon fallido")
    head = _git(runner, clone, "rev-parse", "HEAD").stdout.strip()
    if head != tip:
        raise StartError(f"HEAD del clon discrepante: {head} != {tip}")


def _load_roster(path: Path) -> dict[str, Any]:
    """Read one runtime roster without translating its schema."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StartError(f"roster ilegible: {exc}") from exc
    if not isinstance(payload, dict):
        raise StartError("roster invalido: raiz no es objeto")
    return payload


def _load_families(path: Path) -> dict[str, str]:
    """Load backend families from the versioned ensemble registry."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StartError(f"agents config ilegible: {exc}") from exc
    registry = payload.get("ensemble_registry") if isinstance(payload, dict) else None
    backends = registry.get("backend_keys") if isinstance(registry, dict) else None
    if not isinstance(backends, dict):
        raise StartError("agents config invalido: falta backend_keys")
    return {
        key: entry["family"]
        for key, entry in backends.items()
        if isinstance(key, str)
        and isinstance(entry, dict)
        and isinstance(entry.get("family"), str)
        and entry["family"].strip()
    }


def _roster_reviewer(session: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the session reviewer dispatch contract."""
    reviewer = session.get("revisor")
    if not isinstance(reviewer, dict) or not isinstance(
        reviewer.get("backend_key"), str
    ):
        raise StartError("roster invalido: falta revisor")
    if reviewer.get("channel") != "loop-round":
        raise StartError("revisor invalido: channel debe ser loop-round")
    if not isinstance(reviewer.get("profile"), str) or not reviewer["profile"].strip():
        raise StartError("revisor invalido: falta profile")
    return reviewer


def _roster_candidates(
    roster: dict[str, Any],
    *,
    session_type: str,
    phase: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Extract the real roster phase, revisor and exclusion map."""
    session_types = roster.get("session_types")
    if not isinstance(session_types, dict):
        raise StartError("roster invalido: falta session_types")
    session = session_types.get(session_type)
    if not isinstance(session, dict):
        raise StartError(f"roster invalido: falta session_type {session_type}")
    lenses_by_phase = session.get("lenses")
    if not isinstance(lenses_by_phase, dict):
        raise StartError("roster invalido: falta lenses")
    if phase not in lenses_by_phase:
        raise StartError(f"roster invalido: falta fase {phase}")
    candidates = lenses_by_phase[phase]
    if not isinstance(candidates, list):
        raise StartError(f"roster invalido: fase no es lista: {phase}")
    reviewer = _roster_reviewer(session)
    excluded = roster.get("excluded_lenses")
    if not isinstance(excluded, dict):
        raise StartError("roster invalido: excluded_lenses no es dict")
    if not candidates:
        raise StartError(f"sin lentes revisoras para fase: {phase}")
    return candidates, reviewer, excluded


def _eligible_lenses(
    roster: dict[str, Any],
    *,
    session_type: str,
    phase: str,
    builder_family: str,
    families: dict[str, str],
) -> list[dict[str, Any]]:
    """Validate the runtime roster and annotate per-lens eligibility."""
    candidates, reviewer, excluded = _roster_candidates(
        roster, session_type=session_type, phase=phase
    )
    reviewer_key = reviewer["backend_key"]
    keys = []
    for lens in candidates:
        if not isinstance(lens, dict) or not isinstance(lens.get("backend_key"), str):
            raise StartError("lente sin backend_key")
        if not isinstance(lens.get("profile"), str) or not lens["profile"].strip():
            raise StartError(f"lente sin profile: {lens['backend_key']}")
        keys.append(lens["backend_key"])
    if len(set(keys)) != len(keys):
        raise StartError("par de lentes duplicado")
    valid = []
    for lens in candidates:
        key = lens["backend_key"]
        if key in excluded:
            raise StartError(f"lente excluida: {key}")
        family = families.get(key)
        if family == builder_family:
            raise StartError(f"lente de la familia del Builder: {key}")
        if key == reviewer_key:
            raise StartError(f"lente duplica al Revisor: {key}")
        valid.append(
            {
                "backend_key": key,
                "profile": lens["profile"],
                "family": family,
                "dispatch_role": "challenger",
                "role": "lens",
                "status": "OK" if family is not None else "NO_LEGIBLE",
            }
        )
    reviewer_family = families.get(reviewer_key)
    if reviewer_key in excluded:
        raise StartError(f"lente excluida: {reviewer_key}")
    valid.append(
        {
            "backend_key": reviewer_key,
            "profile": reviewer["profile"],
            "family": reviewer_family,
            "dispatch_role": "challenger",
            "role": "revisor",
            "status": "OK" if reviewer_family is not None else "NO_LEGIBLE",
        }
    )
    return valid


def _scorecard_row(
    project: Path,
    *,
    ticket: str,
    phase: str,
    loop_id: str,
    key: str,
    tip: str,
    nonce: str,
    role: str,
    minimum_matches: int = 0,
) -> dict[str, Any]:
    """Read one scorecard row and turn evidence gaps into a lens status."""
    path = project / ".agent" / "runtime" / "ensemble" / "scorecard.jsonl"
    try:
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"backend_key": key, "role": role, "status": "SIN_RECIBO"}
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("event") == "ronda"
        and row.get("ticket") == ticket
        and row.get("phase") == phase
        and row.get("loop_id") == loop_id
        and row.get("backend_key") == key
        and row.get("commit_sha") == tip
        and row.get("challenge_nonce") == nonce
    ]
    if len(matches) <= minimum_matches:
        return {"backend_key": key, "role": role, "status": "SIN_RECIBO"}
    row = matches[-1]
    requested, effective = row.get("model"), row.get("model_reported")
    if not requested or not effective:
        return {
            "backend_key": key,
            "role": role,
            "status": "NO_LEGIBLE",
            "model_requested": requested,
            "model_effective": effective,
        }
    if requested != effective:
        return {
            "backend_key": key,
            "role": role,
            "status": "DISCREPANTE",
            "model_requested": requested,
            "model_effective": effective,
        }
    return {
        "backend_key": key,
        "role": role,
        "status": "OK",
        "model_requested": requested,
        "model_effective": effective,
    }


def _scorecard_match_count(
    project: Path,
    *,
    ticket: str,
    phase: str,
    loop_id: str,
    key: str,
    tip: str,
    nonce: str,
) -> int:
    """Count current seven-field scorecard matches, failing closed on bad input."""
    path = project / ".agent" / "runtime" / "ensemble" / "scorecard.jsonl"
    try:
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError):
        return 0
    return sum(
        1
        for row in rows
        if isinstance(row, dict)
        and row.get("event") == "ronda"
        and row.get("ticket") == ticket
        and row.get("phase") == phase
        and row.get("loop_id") == loop_id
        and row.get("backend_key") == key
        and row.get("commit_sha") == tip
        and row.get("challenge_nonce") == nonce
    )


def start_ticket(
    *,
    ticket: str,
    base: str,
    tip: str,
    source_repo: str,
    clone_dir: str,
    output_dir: str,
    roster_path: str,
    session_type: str,
    agents_config: str,
    builder_family: str,
    project_root: str,
    dispatcher: str,
    python: str,
    loop_id: str,
    phase: str,
    challenge_nonce: str,
    runner: Runner = subprocess.run,
) -> Path:
    """Clone, build a bundle, dispatch roster lenses, and write a receipt."""
    values = (
        ticket,
        base,
        tip,
        source_repo,
        clone_dir,
        output_dir,
        roster_path,
        session_type,
        agents_config,
        builder_family,
        project_root,
        dispatcher,
        python,
        loop_id,
        phase,
        challenge_nonce,
    )
    if any(not str(value).strip() for value in values):
        raise StartError("todos los argumentos son obligatorios")
    source = _path(source_repo, directory=True)
    roster_path_obj = _path(roster_path)
    agents_config_path = _path(agents_config)
    dispatcher_path = _path(dispatcher)
    project = _path(project_root, directory=True)
    clone = Path(clone_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    base_sha = _commit(runner, source, base)
    tip_sha = _commit(runner, source, tip)
    _clone_at_tip(runner, source, clone, tip_sha)
    diff = _git(runner, clone, "diff", base_sha, tip_sha)
    if diff.returncode:
        raise StartError("diff del clon fallido")
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / f"{ticket}.md"
    bundle.write_text(
        f"# BUNDLE {ticket}\nBASE: {base_sha}\nTIP: {tip_sha}\n\n{diff.stdout}",
        encoding="utf-8",
        newline="\n",
    )
    results: list[dict[str, Any]] = []
    families = _load_families(agents_config_path)
    planned_lenses = _eligible_lenses(
        _load_roster(roster_path_obj),
        session_type=session_type,
        phase=phase,
        builder_family=builder_family,
        families=families,
    )
    for planned in planned_lenses:
        current_lenses = _eligible_lenses(
            _load_roster(roster_path_obj),
            session_type=session_type,
            phase=phase,
            builder_family=builder_family,
            families=families,
        )
        current_by_key = {lens["backend_key"]: lens for lens in current_lenses}
        key = planned["backend_key"]
        lens = current_by_key.get(key)
        if lens is None:
            raise StartError(f"roster cambio antes del despacho: {key}")
        current_composition = [
            (item["backend_key"], item["role"], item["profile"])
            for item in current_lenses
        ]
        planned_composition = [
            (item["backend_key"], item["role"], item["profile"])
            for item in planned_lenses
        ]
        if current_composition != planned_composition:
            raise StartError(
                "roster cambio antes del despacho: composicion distinta "
                f"{current_composition!r} != {planned_composition!r}"
            )
        if lens["status"] == "NO_LEGIBLE":
            results.append(
                {"backend_key": key, "role": planned["role"], "status": "NO_LEGIBLE"}
            )
            continue
        before_matches = _scorecard_match_count(
            project,
            ticket=ticket,
            phase=phase,
            loop_id=loop_id,
            key=key,
            tip=tip_sha,
            nonce=challenge_nonce,
        )
        command = [
            python,
            str(dispatcher_path),
            "loop-round",
            "--profile",
            lens["profile"],
            "--content-file",
            str(bundle),
            "--ticket",
            ticket,
            "--task-type",
            "code-review",
            "--rol",
            lens["dispatch_role"],
            "--phase",
            phase,
            "--loop-id",
            loop_id,
            "--backend-key",
            key,
            "--data-sensitivity",
            "public",
            "--commit-sha",
            tip_sha,
            "--challenge-nonce",
            challenge_nonce,
            "--project-root",
            str(project),
        ]
        result = _run(runner, command, cwd=clone)
        if result.returncode:
            results.append(
                {
                    "backend_key": key,
                    "role": planned["role"],
                    "status": "FALLO_RC",
                    "rc": result.returncode,
                }
            )
            continue
        results.append(
            _scorecard_row(
                project,
                ticket=ticket,
                phase=phase,
                loop_id=loop_id,
                key=key,
                tip=tip_sha,
                nonce=challenge_nonce,
                role=planned["role"],
                minimum_matches=before_matches,
            )
        )
    receipt = output / "start_receipt.json"
    receipt.write_text(
        json.dumps({"ticket": ticket, "tip": tip_sha, "lenses": results}, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "ticket",
        "base",
        "tip",
        "source-repo",
        "clone-dir",
        "output-dir",
        "roster-path",
        "session-type",
        "agents-config",
        "builder-family",
        "project-root",
        "dispatcher",
        "python",
        "loop-id",
        "phase",
        "challenge-nonce",
    ):
        parser.add_argument(f"--{name}", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        receipt = start_ticket(**vars(_parser().parse_args(argv)))
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        if any(row.get("status") != "OK" for row in payload["lenses"]):
            print(f"START_FAIL: lente no OK en {receipt}", file=sys.stderr)
            return 1
    except StartError as exc:
        print(f"START_FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"START_OK: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
