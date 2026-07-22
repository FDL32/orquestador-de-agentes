"""Tests del exportador de review packet hacia el ensemble (WOT-2026-027p).

Contrato T-027P-001 (frozen): el exportador REUTILIZA el ensamblado que YA
existe (ReviewBridge._build_review_prompt) y produce un packet con:
  - >=1 seccion ## PROBE con ```receipt (command/exit_code) que
    check_bundle_receipts valida rc=0 (DoD-b);
  - una seccion ## UNIVERSE MANIFEST con las rutas de compute_code_universe
    + sha256 agregado, verificable con review_bundle_contract rc=0 (DoD-c);
  - cache por (ticket, motor_head, destino_head, sha256(work_plan)): segunda
    invocacion identica -> CACHE_HIT y sha256 del packet identico (DoD-d);
  - mutation DoD-e: omitir una ruta del manifest -> review_bundle_contract
    exit 1 nombrando faltantes.

Hermetico donde se puede (tmp_path como workspace sintetico con work_plan
minimo); el universo se computa contra el MOTOR REAL (read-only, git ls-tree
de HEAD): ese acoplamiento es deliberado -- el contrato exige "no recortado
bajo el universo" del motor real, y un fixture-universo seria el falso-verde
que 026k llama bundle recortado.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    path = _MOTOR_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


erp = _load("export_review_packet")
cbr = _load("check_bundle_receipts")
rbc = _load("review_bundle_contract")


@pytest.fixture()
def fake_workspace(tmp_path: Path) -> Path:
    """Workspace sintetico minimo: colaboracion canonica + link al motor real.

    El link apunta al MOTOR REAL para que la verificacion de coherencia
    motor-root (fail-closed del contrato) pase con --motor-root real.
    """
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "work_plan.md").write_text(
        "# Work Plan\n**ID:** WOT-2026-027p\n**Estado:** IN_PROGRESS\n"
        "deliverable_type: code\n",
        encoding="utf-8",
    )
    (collab / "STATE.md").write_text("estado sintetico\n", encoding="utf-8")
    (collab / "TURN.md").write_text("| **ROL** | **BUILDER** |\n", encoding="utf-8")
    (collab / "execution_log.md").write_text(
        "## WOT-2026-027p\nlog sintetico\n", encoding="utf-8"
    )
    config = tmp_path / ".agent" / "config"
    config.mkdir(parents=True)
    (config / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(_MOTOR_ROOT)}), encoding="utf-8"
    )
    (tmp_path / ".agent" / "runtime").mkdir(parents=True)
    # El workspace real ES un repo git y destino_head es componente de la
    # clave de cache: el fixture lo replica con su PROPIO .git (vector git
    # CEM: sin el, cualquier walk-up hablaria del arbol real, no del fixture).
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env={**__import__("os").environ, **env},
    )
    return tmp_path


def _run_cli(workspace: Path, *extra: str) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_MOTOR_ROOT / "scripts" / "export_review_packet.py"),
        "--ticket",
        "WOT-2026-027p",
        "--motor-root",
        str(_MOTOR_ROOT),
        "--project-root",
        str(workspace),
        *extra,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", cwd=_MOTOR_ROOT
    )


def _packet_path_from_stdout(stdout: str) -> Path:
    for line in stdout.splitlines():
        line = line.strip()
        if line.endswith(".md") and "review_packets" in line:
            # la ultima palabra de la linea es la ruta
            return Path(line.split()[-1])
    raise AssertionError(f"stdout sin ruta de packet: {stdout!r}")


def test_export_generates_packet_dod_a(fake_workspace: Path):
    """DoD-a: un comando exporta el packet sin intervencion manual, exit 0."""
    proc = _run_cli(fake_workspace)
    assert proc.returncode == 0, proc.stderr
    packet = _packet_path_from_stdout(proc.stdout)
    assert packet.is_file()
    text = packet.read_text(encoding="utf-8")
    assert "## UNIVERSE MANIFEST" in text
    assert "## PROBE" in text


def test_packet_passes_receipt_guard_dod_b(fake_workspace: Path):
    """DoD-b: el packet exportado pasa check_bundle_receipts rc=0."""
    proc = _run_cli(fake_workspace)
    assert proc.returncode == 0, proc.stderr
    packet = _packet_path_from_stdout(proc.stdout)
    rc = cbr.run(["--bundle", str(packet), "--root", str(_MOTOR_ROOT)])
    assert rc == 0


def test_packet_manifest_covers_universe_dod_c(fake_workspace: Path, tmp_path: Path):
    """DoD-c: las rutas del manifest cubren el universo (no recortado)."""
    proc = _run_cli(fake_workspace)
    assert proc.returncode == 0, proc.stderr
    packet = _packet_path_from_stdout(proc.stdout)
    manifest_paths = erp.extract_manifest_paths(packet.read_text(encoding="utf-8"))
    listing = tmp_path / "bundle_paths.txt"
    listing.write_text("\n".join(sorted(manifest_paths)), encoding="utf-8")
    rc = rbc.main(["--repo-root", str(_MOTOR_ROOT), "--bundle-file", str(listing)])
    assert rc == 0


def test_second_invocation_cache_hit_dod_d(fake_workspace: Path):
    """DoD-d: segunda invocacion identica -> CACHE_HIT + sha256 identico."""
    first = _run_cli(fake_workspace)
    assert first.returncode == 0, first.stderr
    packet = _packet_path_from_stdout(first.stdout)
    sha_first = hashlib.sha256(packet.read_bytes()).hexdigest()

    second = _run_cli(fake_workspace)
    assert second.returncode == 0, second.stderr
    assert "CACHE_HIT" in second.stdout
    sha_second = hashlib.sha256(packet.read_bytes()).hexdigest()
    assert sha_first == sha_second


def test_workplan_change_invalidates_cache(fake_workspace: Path):
    """Cambio en un componente de la clave (work_plan) -> regenera, no HIT."""
    first = _run_cli(fake_workspace)
    assert first.returncode == 0, first.stderr
    wp = fake_workspace / ".agent" / "collaboration" / "work_plan.md"
    wp.write_text(wp.read_text(encoding="utf-8") + "\nlinea nueva\n", encoding="utf-8")
    second = _run_cli(fake_workspace)
    assert second.returncode == 0, second.stderr
    assert "CACHE_HIT" not in second.stdout


def test_mutation_truncated_manifest_rejected_dod_e(
    fake_workspace: Path, tmp_path: Path
):
    """DoD-e (mutation): omitir una ruta del manifest -> exit 1 con faltantes.

    La victima es el veredicto de review_bundle_contract sobre el manifest
    RECORTADO: si el invariante no mirara los faltantes, este par no podria
    distinguir el recorte (falso-verde de bundle recortado, 026k).
    """
    proc = _run_cli(fake_workspace)
    assert proc.returncode == 0, proc.stderr
    packet = _packet_path_from_stdout(proc.stdout)
    manifest_paths = sorted(
        erp.extract_manifest_paths(packet.read_text(encoding="utf-8"))
    )
    assert manifest_paths, "manifest vacio: no hay universo que recortar"

    # Par de exit codes: completo -> 0; recortado (sin la primera ruta) -> 1.
    full = tmp_path / "full.txt"
    full.write_text("\n".join(manifest_paths), encoding="utf-8")
    rc_full = rbc.main(["--repo-root", str(_MOTOR_ROOT), "--bundle-file", str(full)])
    assert rc_full == 0

    truncated = tmp_path / "truncated.txt"
    truncated.write_text("\n".join(manifest_paths[1:]), encoding="utf-8")
    rc_trunc = rbc.main(
        ["--repo-root", str(_MOTOR_ROOT), "--bundle-file", str(truncated)]
    )
    assert rc_trunc == 1


def test_ticket_mismatch_fails_closed(fake_workspace: Path):
    """El work_plan vivo describe OTRO ticket -> exit !=0, nada se exporta.

    Hallazgo MAJOR-1 del MANAGER_REVIEW (2026-07-22): el bridge lee
    work_plan/STATE/TURN VERBATIM y solo usa `ticket_id` para la seccion de
    execution_log. Sin este guard, pedir --ticket WOT-2026-027p con el
    work_plan de 026k producia un packet formalmente valido (receipts OK,
    manifest completo) cuyo CONTENIDO era el plan y el veredicto de otro
    ticket ya cerrado. Un DoD que solo mira exit codes no lo ve.
    """
    wp = fake_workspace / ".agent" / "collaboration" / "work_plan.md"
    wp.write_text(
        wp.read_text(encoding="utf-8").replace(
            "**ID:** WOT-2026-027p", "**ID:** WOT-2026-026k"
        ),
        encoding="utf-8",
    )
    proc = _run_cli(fake_workspace)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "WOT-2026-026k" in combined, combined


def test_probe_receipts_carry_observed_exit_codes(fake_workspace: Path):
    """Los receipts declaran comandos REPRODUCIBLES y rc OBSERVADO.

    Hallazgo MAJOR-2: un `exit_code: 0` hardcodeado satisface
    check_bundle_receipts por construccion y reintroduce el HUECO-1 que ese
    guard existe para cerrar (una afirmacion sin recibo real). Este test
    pinnea que el command sea un comando de shell re-ejecutable, no una
    llamada Python interna que el lector no puede reproducir.
    """
    proc = _run_cli(fake_workspace)
    assert proc.returncode == 0, proc.stderr
    text = _packet_path_from_stdout(proc.stdout).read_text(encoding="utf-8")
    # Acotado a las secciones PROBE que ESTE script genera: el resto del
    # packet es contexto canonico del bridge (work_plan, diff, memoria) y
    # puede contener cualquier texto sin que sea un receipt del exportador.
    probes = text.split("## UNIVERSE MANIFEST", 1)[0]
    assert "command: git ls-tree" in probes
    assert "command: git rev-parse HEAD" in probes
    # Ninguna llamada Python interna presentada como comando ejecutable.
    assert "command: review_bundle_contract." not in probes


def test_motor_root_mismatch_fails_closed(fake_workspace: Path, tmp_path: Path):
    """Coherencia motor-root (objecion Codex): link != --motor-root -> exit !=0."""
    link = fake_workspace / ".agent" / "config" / "motor_destination_link.json"
    other = tmp_path / "otro_motor"
    other.mkdir()
    link.write_text(json.dumps({"motor_root": str(other)}), encoding="utf-8")
    proc = _run_cli(fake_workspace)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "motor" in combined.lower()
