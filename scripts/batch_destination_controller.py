"""Agnostic batch controller for multiple motor destinations.

Before:
    A caller has several `repo_destino` directories that each use the motor as a
    portable tool, plus the absolute path of the motor itself. The caller wants a
    per-destination readiness map to prepare repos for remote publication.
During:
    For each destination the controller inspects adoption, contract-formation
    state, optional read-only gates (validate + memory status with
    AGENT_PROJECT_ROOT set per repo), local integration, CI-pending closeouts and
    publication evidence. It records evidence per repo; it never aggregates green.
After:
    It emits a JSON + Markdown manifest. It treats the motor as read-only tooling
    and never writes inside any destination beyond the requested --out-dir.

Publication is modelled in four layers that never collapse into one another
(see prompts/audit_git_publication.md, "no se sustituyen"):

  1. integrated_local        -> check_destino_publish_ready.py (live-state gate)
  2. publication_classified  -> classify_publication.py verdict ([RELATO] only)
  3. publication_audit_passed-> audit_git_publication.md Pass B closeout (evidence)
  4. publishable             -> true only when all three above hold

The classify_publication verdict is RELATO, not final evidence: this controller
never sets publishable=true from the deterministic script alone. The adversarial
Pass B (audit_git_publication.md) is performed by an agent, not by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLANNING_FILES = (
    ".agent/planning/repo_charter.md",
    ".agent/planning/plan_graph.md",
    ".agent/planning/ticket_contracts.md",
)
PUBLISH_READY_VERDICT = "LISTO_PARA_PUBLICAR"


@dataclass(frozen=True)
class RepoSpec:
    """One destination repo declared by the caller.

    Before: a mapping with at least `path`. During: normalized into a spec.
    After: immutable record consumed by inspect_repo.
    """

    path: Path
    name: str
    shared_surfaces: tuple[str, ...] = ()
    authorized_motor_write: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> RepoSpec:
        """Before: raw dict. During: read fields. After: RepoSpec."""
        path = Path(str(raw["path"]))
        name = str(raw.get("name") or path.name)
        surfaces = tuple(str(item) for item in raw.get("shared_surfaces", []))
        return cls(
            path=path,
            name=name,
            shared_surfaces=surfaces,
            authorized_motor_write=bool(raw.get("authorized_motor_write", False)),
        )


def _now_iso() -> str:
    """Before: none. During: read UTC clock. After: ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    """Before: path exists. During: parse JSON. After: object dict."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Before: payload is JSON-safe. During: create parent. After: write UTF-8."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _evidence_path(root: Path, relative: str) -> dict[str, Any]:
    """Before: root + relative path. During: stat. After: path-evidence dict."""
    path = root / relative
    exists = path.exists()
    evidence: dict[str, Any] = {
        "type": "path",
        "path": str(path),
        "exists": exists,
    }
    if exists and path.is_file():
        evidence["bytes"] = path.stat().st_size
    return evidence


def _run_command(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Before: command is read-only. During: run. After: command-evidence dict."""
    result = subprocess.run(  # noqa: S603
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "type": "command",
        "command": command,
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _agent_link_motor_root(root: Path) -> str | None:
    """Before: root may hold a link. During: read JSON. After: motor root or None."""
    link = root / ".agent/config/motor_destination_link.json"
    if not link.exists():
        return None
    try:
        data = _read_json(link)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    value = data.get("motor_root") or data.get("MOTOR_ROOT") or data.get("repo_motor")
    return str(value) if value else None


def _ticket_contract_frozen(root: Path) -> bool:
    """Before: planning may exist. During: scan. After: True if a frozen contract."""
    contracts = root / ".agent/planning/ticket_contracts.md"
    if not contracts.exists():
        return False
    text = contracts.read_text(encoding="utf-8", errors="replace").lower()
    return "status: frozen" in text or "status=frozen" in text


def _validate_is_clean(stdout: str) -> bool:
    """Decide whether `agent_controller --validate --json` output is 0/0.

    Before:
        stdout is the raw text of the validate command.
    During:
        Parses JSON and counts errors/warnings. The canonical shape exposes
        `errors` and `warnings` as DICTS of category -> list (see
        check_destino_publish_ready.py:_count_errors and orchestrator_pipeline.md
        which requires `warnings: {}`). Older shapes may use ints or lists; all
        are reduced to a total count so a non-empty container is never read as 0.
    After:
        Returns True only when both totals are exactly 0.
    """
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return _count_items(payload.get("errors")) == 0 and (
        _count_items(payload.get("warnings")) == 0
    )


def _count_items(value: Any) -> int:
    """Before: errors/warnings field of unknown shape. During: normalize.
    After: total count (dict of lists, list, int, or None all supported)."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return sum(_count_items(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 1


def _latest_manifest_verdict(root: Path) -> str | None:
    """Before: reports dir may exist. During: read newest manifest.
    After: classify_publication verdict ([RELATO]) or None."""
    reports = root / "orchestrator_pipeline/reports"
    if not reports.exists():
        return None
    manifests = sorted(reports.glob("publication_manifest*.json"))
    for manifest in reversed(manifests):
        try:
            data = _read_json(manifest)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        verdict = data.get("verdict")
        if verdict:
            return str(verdict)
    return None


def _publication_audit_passed(root: Path) -> bool:
    """Detect a completed audit_git_publication.md Pass B for this repo.

    Before:
        reports dir may contain a publication audit closeout written by an agent
        following prompts/audit_git_publication.md (NOT the deterministic script).
    During:
        Looks for a publication audit report whose verdict is LISTO_PARA_PUBLICAR.
        The script verdict alone is RELATO and never satisfies this check.
    After:
        Returns True only when adversarial Pass B evidence exists on disk.
    """
    reports = root / "orchestrator_pipeline/reports"
    if not reports.exists():
        return False
    for report in sorted(reports.glob("publication_audit*.json")):
        try:
            data = _read_json(report)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if str(data.get("verdict")) == PUBLISH_READY_VERDICT:
            return True
    return False


def _has_closed_pending_ci(root: Path) -> bool:
    """Before: reports dir may exist. During: scan closeouts.
    After: True if any closeout is CI-pending."""
    reports = root / "orchestrator_pipeline/reports"
    if not reports.exists():
        return False
    for closeout in reports.glob("closeout_*.md"):
        text = closeout.read_text(encoding="utf-8", errors="replace")
        if "CLOSED_PENDING_CI" in text or "PENDIENTE-POST-PUSH" in text:
            return True
    return False


def inspect_repo(
    spec: RepoSpec,
    motor_root: Path,
    run_readonly_gates: bool = False,
) -> dict[str, Any]:
    """Inspect one destination and record evidence.

    Before:
        spec.path may or may not be an adopted destination; motor_root is the
        portable motor.
    During:
        Collects path evidence; optionally runs validate + memory status with
        AGENT_PROJECT_ROOT set to this repo; derives the four publication layers.
    After:
        Returns a per-repo record with states, evidence and next_action. No write
        occurs inside the destination.
    """
    root = spec.path.resolve()
    evidence: list[dict[str, Any]] = [
        _evidence_path(root, ".agent/config/motor_destination_link.json"),
        _evidence_path(root, "PROJECT.md"),
    ]
    evidence.extend(_evidence_path(root, relative) for relative in PLANNING_FILES)

    agent_link_motor = _agent_link_motor_root(root)
    planning_ready = all((root / relative).exists() for relative in PLANNING_FILES)
    contract_ready = planning_ready and _ticket_contract_frozen(root)
    adopted = agent_link_motor is not None

    validate_evidence: dict[str, Any] | None = None
    memory_evidence: dict[str, Any] | None = None
    if run_readonly_gates:
        env = dict(os.environ)
        env["AGENT_PROJECT_ROOT"] = str(root)
        validate_evidence = _run_command(
            [
                "python",
                str(motor_root / ".agent/agent_controller.py"),
                "--validate",
                "--json",
                "--project-root",
                str(root),
            ],
            cwd=root,
            env=env,
        )
        evidence.append(validate_evidence)
        memory_evidence = _run_command(
            ["python", str(motor_root / "scripts/memory_context.py"), "--status"],
            cwd=root,
            env=env,
        )
        evidence.append(memory_evidence)

    agent_project_root_verified = False
    if memory_evidence is not None:
        combined = (
            f"{memory_evidence.get('stdout', '')}\n{memory_evidence.get('stderr', '')}"
        )
        agent_project_root_verified = (
            memory_evidence["exit_code"] == 0 and str(root) in combined
        )

    validate_clean = False
    if validate_evidence is not None and validate_evidence["exit_code"] == 0:
        validate_clean = _validate_is_clean(str(validate_evidence.get("stdout") or ""))

    classified_verdict = _latest_manifest_verdict(root)
    audit_passed = _publication_audit_passed(root)
    closed_pending_ci = _has_closed_pending_ci(root)

    states = {
        "adopted": adopted,
        "contract_ready": contract_ready,
        "contract_formation_required": not contract_ready,
        "agent_project_root_verified": agent_project_root_verified,
        "integrated_local": validate_clean,
        "publication_classified": classified_verdict == PUBLISH_READY_VERDICT,
        "publication_audit_passed": audit_passed,
        "closed_pending_ci": closed_pending_ci,
    }
    # publishable requires ALL three layers; the classify verdict is only RELATO.
    states["publishable"] = (
        states["integrated_local"]
        and states["publication_classified"]
        and states["publication_audit_passed"]
    )

    return {
        "repo": spec.name,
        "path": str(root),
        "generated_at": _now_iso(),
        "states": states,
        "publication_classified_verdict": classified_verdict,
        "publication_verdict_is_relato": True,
        "motor": {
            "motor_root_declared_by_repo": agent_link_motor,
            "motor_root_expected": str(motor_root.resolve()),
            "authorized_motor_write": spec.authorized_motor_write,
        },
        "shared_surfaces": list(spec.shared_surfaces),
        "evidence": evidence,
        "next_action": _next_action(
            states=states,
            classified_verdict=classified_verdict,
            ran_gates=run_readonly_gates,
        ),
    }


def _next_action(
    *,
    states: dict[str, bool],
    classified_verdict: str | None,
    ran_gates: bool,
) -> str:
    """Before: per-repo states. During: pick the earliest unmet step.
    After: a single next-action token."""
    if not states["adopted"]:
        return "ADOPT_DESTINATION"
    if not states["contract_ready"]:
        return "RUN_CONTRACT_FORMATION"
    if not ran_gates:
        # Live-state integration is unproven without the read-only gates, so we
        # cannot reason about publication yet: integrated_local is the floor of
        # the four-layer model. Ask the caller to run the gates first.
        return "RUN_READONLY_GATES"
    if not states["agent_project_root_verified"]:
        return "FIX_AGENT_PROJECT_ROOT_FOR_REPO"
    if not states["integrated_local"]:
        return "RUN_ORCHESTRATOR_PIPELINE_FOR_REPO"
    if states["closed_pending_ci"]:
        return "WAIT_FOR_CI_RECHECK"
    if classified_verdict != PUBLISH_READY_VERDICT:
        return "RUN_PUBLICATION_CLASSIFICATION_FULL_HISTORY"
    if not states["publication_audit_passed"]:
        return "RUN_AUDIT_GIT_PUBLICATION_PASS_B"
    return "READY_FOR_REMOTE_PUBLICATION"


def add_inter_repo_recheck(manifest: dict[str, Any]) -> None:
    """Before: manifest has repos[]. During: group shared surfaces.
    After: manifest gains inter_repo_recheck describing cross-repo overlaps."""
    owners: dict[str, list[str]] = {}
    for repo in manifest["repos"]:
        for surface in repo.get("shared_surfaces", []):
            owners.setdefault(surface, []).append(str(repo["repo"]))

    overlaps = [
        {"surface": surface, "repos": repos}
        for surface, repos in sorted(owners.items())
        if len(repos) > 1
    ]
    manifest["inter_repo_recheck"] = {
        "required": bool(overlaps),
        "overlaps": overlaps,
        "rule": (
            "When a repo closes after changing shared credentials, services, data "
            "contracts, or generated artifacts, re-check pending premises in every "
            "other repo listed for the same surface."
        ),
    }


def build_manifest(
    specs: list[RepoSpec],
    motor_root: Path,
    run_readonly_gates: bool = False,
) -> dict[str, Any]:
    """Before: specs + motor root. During: inspect each repo. After: full manifest."""
    manifest = {
        "schema": "external-destination-batch-manifest-v1",
        "generated_at": _now_iso(),
        "motor_root": str(motor_root.resolve()),
        "repos": [
            inspect_repo(spec, motor_root, run_readonly_gates=run_readonly_gates)
            for spec in specs
        ],
    }
    add_inter_repo_recheck(manifest)
    return manifest


def write_markdown_report(path: Path, manifest: dict[str, Any]) -> None:
    """Before: manifest built. During: render table. After: write Markdown."""
    lines = [
        "# External Destination Batch Manifest",
        "",
        f"Generated: `{manifest['generated_at']}`",
        f"Motor root: `{manifest['motor_root']}`",
        "",
        "## Repos",
        "",
        "| Repo | Adopted | Contract | Local | Classified | Audited | CI Pending | Publishable | Next |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for repo in manifest["repos"]:
        states = repo["states"]
        lines.append(
            "| {repo} | {adopted} | {contract} | {local} | {classified} | "
            "{audited} | {ci} | {publishable} | {next_action} |".format(
                repo=repo["repo"],
                adopted=_yesno(states["adopted"]),
                contract=_yesno(states["contract_ready"]),
                local=_yesno(states["integrated_local"]),
                classified=_yesno(states["publication_classified"]),
                audited=_yesno(states["publication_audit_passed"]),
                ci=_yesno(states["closed_pending_ci"]),
                publishable=_yesno(states["publishable"]),
                next_action=repo["next_action"],
            )
        )
    lines.extend(["", "## Inter-Repo Recheck", ""])
    recheck = manifest["inter_repo_recheck"]
    lines.append(f"Required: `{_yesno(recheck['required'])}`")
    lines.extend(
        f"- `{overlap['surface']}`: {', '.join(overlap['repos'])}"
        for overlap in recheck["overlaps"]
    )
    lines.extend(
        [
            "",
            "## Evidence & Publication Rules",
            "",
            "- Each repo row is backed by its own `evidence` array in the JSON "
            "manifest; do not promote aggregate claims without per-repo `path:` "
            "or `command:` evidence.",
            "- `Classified` is the classify_publication.py verdict and is "
            "**[RELATO]**, not final evidence (see audit_git_publication.md).",
            "- `Publishable` is true only when Local + Classified + Audited all "
            "hold; the deterministic script alone never declares it.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _yesno(value: bool) -> str:
    """Before: bool. During: map. After: 'yes'/'no'."""
    return "yes" if value else "no"


def _load_specs(path: Path) -> list[RepoSpec]:
    """Before: JSON file path. During: parse. After: list of RepoSpec."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    repos = data.get("repos") if isinstance(data, dict) else data
    if not isinstance(repos, list):
        raise ValueError("Expected a JSON object with repos[] or a list of repos")
    return [RepoSpec.from_mapping(item) for item in repos]


def build_parser() -> argparse.ArgumentParser:
    """Before: none. During: define CLI. After: parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repos", type=Path, required=True, help="JSON file with repos[]"
    )
    parser.add_argument("--motor-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--run-readonly-gates",
        action="store_true",
        help="Run validate and memory status with AGENT_PROJECT_ROOT set per repo.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: argv optional. During: build manifest. After: write outputs, exit 0."""
    args = build_parser().parse_args(argv)
    specs = _load_specs(args.repos)
    manifest = build_manifest(
        specs,
        args.motor_root,
        run_readonly_gates=args.run_readonly_gates,
    )
    json_path = args.out_dir / "batch_manifest.json"
    md_path = args.out_dir / "batch_manifest.md"
    _write_json(json_path, manifest)
    write_markdown_report(md_path, manifest)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
