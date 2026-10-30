"""WOT-2026-143a (DoD 2): `scripts/flight/integrate_ticket.py` y el paso de cierre
`integration_receipts`.

Sin mocks del git ni del audit: repos git REALES (motor con una rama candidata en un
worktree propio, destino aparte con scorecard/emitted sinteticos con la forma real). Cada
rama del wrapper tiene su control: el mismo mundo con evidencia integra, sin ella no.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts import check_loop_execution as cle  # noqa: E402
from scripts.closeout_steps import gates  # noqa: E402
from scripts.flight import integrate_ticket as it  # noqa: E402
from scripts.session_closeout import StepResult  # noqa: E402


TICKET = "WOT-2026-999z"
WRAPPER = _MOTOR_ROOT / "scripts" / "flight" / "integrate_ticket.py"
_TS_EMIT = "2026-10-11T10:00:00+00:00"
_TS_ROUND = "2026-10-11T10:05:00+00:00"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, rel: str, content: str, message: str) -> str:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(content, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@dataclass
class World:
    motor: Path
    cand: Path
    destino: Path
    base: str
    tip: str


def _write_evidence(destino: Path, sha: str) -> None:
    ensemble = destino / ".agent" / "runtime" / "ensemble"
    ensemble.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "event": "ronda",
            "commit_sha": sha,
            "backend_key": bk,
            "challenge_nonce": "N-143a",
            "ts": _TS_ROUND,
            "output_chars": 2134,
            "evidencia": "veredicto de la lente",
        }
        for bk in ("BA03", "BA07")
    ]
    (ensemble / "scorecard.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    emitted = {
        "ts": _TS_EMIT,
        "issuer_role": "orchestrator",
        "issuer_backend_key": "BA01",
        "issued_before_ts": _TS_EMIT,
        "commit_sha": sha,
        "loop_id": "L143",
        "challenge_nonce": "N-143a",
    }
    (ensemble / "emitted_nonces.jsonl").write_text(
        json.dumps(emitted) + "\n", encoding="utf-8"
    )


def _world(tmp_path: Path, *, evidence: bool = True) -> World:
    """Motor (rama del vuelo) + worktree candidato con 2 commits del ticket + destino."""
    motor = tmp_path / "motor"
    motor.mkdir()
    _git(motor, "init", "-q")
    _git(motor, "config", "user.email", "t@e.com")
    _git(motor, "config", "user.name", "T")
    base = _commit(motor, "README.md", "# vuelo", "init")
    cand = tmp_path / "cand"
    _git(motor, "worktree", "add", "-q", "-b", "candidate", str(cand))
    _commit(cand, "src/a.py", "x = 1", f"{TICKET}: paso 1")
    tip = _commit(cand, "src/b.py", "x = 2", f"{TICKET}: paso 2")
    destino = tmp_path / "destino"
    (destino / ".agent" / "collaboration").mkdir(parents=True)
    (destino / ".agent" / "collaboration" / "work_plan.md").write_text(
        f"# Work Plan\n\n## Metadata\n- **ID:** {TICKET}\n"
        "- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )
    if evidence:
        _write_evidence(destino, tip)
    return World(motor, cand, destino, base, tip)


def _run(w: World, *extra: str, cwd: Path | None = None):
    return subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--ticket",
            TICKET,
            "--candidate",
            "candidate",
            "--project-root",
            str(w.destino),
            *extra,
        ],
        cwd=cwd or w.motor,
        capture_output=True,
        text=True,
    )


# integrar - positivo
def test_integrate_ff_merges_the_audited_tip_and_writes_the_receipt(tmp_path):
    w = _world(tmp_path)
    rc, lines = it.integrate(TICKET, "candidate", w.destino, w.motor)
    assert rc == 0, lines
    assert lines[0].startswith("OK integrate"), lines
    assert _git(w.motor, "rev-parse", "HEAD") == w.tip
    assert it.receipt_problem(w.destino, w.tip) is None
    receipt = json.loads(it.receipt_path(w.destino, w.tip).read_text(encoding="utf-8"))
    assert receipt["mode"] == "integrate" and receipt["merged"] is True
    assert receipt["base_head"] == w.base and receipt["head_after"] == w.tip
    # el recibo vive FUERA del motor: ningun fichero nuevo, tracked ni no versionado
    assert _git(w.motor, "status", "--porcelain") == ""


def test_audit_in_red_blocks_the_merge_and_leaves_no_receipt(tmp_path):
    """Control del positivo: el MISMO mundo sin evidencia no integra."""
    w = _world(tmp_path, evidence=False)
    rc, lines = it.integrate(TICKET, "candidate", w.destino, w.motor)
    assert rc == 1, lines
    assert "audit del bucle en rojo" in lines[0]
    assert _git(w.motor, "rev-parse", "HEAD") == w.base
    assert not it.receipt_path(w.destino, w.tip).exists()


def test_evidence_on_a_non_tip_commit_does_not_integrate(tmp_path):
    """DoD (5): el bucle sobre el PRIMER commit no acredita el estado final."""
    w = _world(tmp_path, evidence=False)
    first = _git(w.cand, "rev-parse", "HEAD~1")
    _write_evidence(w.destino, first)
    rc, _lines = it.integrate(TICKET, "candidate", w.destino, w.motor)
    assert rc == 1
    assert _git(w.motor, "rev-parse", "HEAD") == w.base


def test_commit_after_the_tip_that_does_not_cite_the_ticket_is_not_integrated(tmp_path):
    w = _world(tmp_path)
    _commit(w.cand, "src/c.py", "x = 3", "arreglo sin ticket")
    rc, lines = it.integrate(TICKET, "candidate", w.destino, w.motor)
    assert rc == 1 and "sin auditar" in lines[0], lines
    assert _git(w.motor, "rev-parse", "HEAD") == w.base


# auto-integracion desde el clon candidato
def test_self_integration_runs_the_wrapper_from_a_checkout_the_flight_does_not_have(
    tmp_path,
):
    """El wrapper vive en el tip que se mergea: el worktree del vuelo no lo tiene. Se corre
    por RUTA desde fuera del vuelo, con cwd en el motor (sin --motor-root)."""
    w = _world(tmp_path)
    assert not (w.motor / "scripts" / "flight" / "integrate_ticket.py").exists()
    r = _run(w)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[0].startswith("OK integrate"), r.stdout
    assert _git(w.motor, "rev-parse", "HEAD") == w.tip
    assert it.receipt_problem(w.destino, w.tip) is None


def test_self_integration_with_audit_in_red_leaves_head_and_receipts_intact(tmp_path):
    w = _world(tmp_path, evidence=False)
    r = _run(w)
    assert r.returncode == 1, r.stdout + r.stderr
    assert _git(w.motor, "rev-parse", "HEAD") == w.base
    assert not (w.destino / it.RECEIPTS_REL).exists()


# fail-closed - rc 2
@pytest.mark.parametrize("variant", ["no_flag", "no_agent_dir"])
def test_missing_project_root_is_rc2_without_merge(tmp_path, capsys, variant):
    w = _world(tmp_path)
    argv = [
        "--ticket",
        TICKET,
        "--candidate",
        "candidate",
        "--motor-root",
        str(w.motor),
    ]
    if variant == "no_agent_dir":
        argv += ["--project-root", str(tmp_path / "vacio")]
    rc = it.main(argv)
    assert rc == 2
    assert capsys.readouterr().out.startswith("NO VERIFICABLE")
    assert _git(w.motor, "rev-parse", "HEAD") == w.base


def test_dirty_tracked_tree_is_rc2_but_untracked_files_do_not_block(tmp_path):
    w = _world(tmp_path)
    (w.motor / "extra_coord.txt").write_text("no versionado", encoding="utf-8")
    (w.motor / "README.md").write_text("# editado", encoding="utf-8")
    rc, lines = it.integrate(TICKET, "candidate", w.destino, w.motor)
    assert rc == 2 and "sucio" in lines[0], lines
    assert _git(w.motor, "rev-parse", "HEAD") == w.base
    _git(w.motor, "checkout", "--", "README.md")
    rc, lines = it.integrate(TICKET, "candidate", w.destino, w.motor)
    assert rc == 0, lines


# attest
def test_attest_audits_an_already_integrated_tip_without_merging(tmp_path):
    w = _world(tmp_path)
    _git(w.motor, "merge", "--ff-only", "candidate")
    rc, lines = it.integrate(TICKET, w.tip, w.destino, w.motor, attest=True)
    assert rc == 0 and lines[0].startswith("OK attest"), lines
    receipt = json.loads(it.receipt_path(w.destino, w.tip).read_text(encoding="utf-8"))
    assert receipt["mode"] == "attest" and receipt["merged"] is False
    assert _git(w.motor, "rev-parse", "HEAD") == w.tip


def test_attest_of_a_tip_that_is_not_an_ancestor_of_head_fails_without_receipt(
    tmp_path,
):
    w = _world(tmp_path)
    rc, lines = it.integrate(TICKET, "candidate", w.destino, w.motor, attest=True)
    assert rc == 1 and "no es ancestro" in lines[0], lines
    assert not it.receipt_path(w.destino, w.tip).exists()


# el recibo y su lector
def _receipt(sha: str, **over) -> dict:
    base = {
        "schema": 1,
        "ticket": TICKET,
        "tip": sha,
        "base_head": "b" * 40,
        "head_after": sha,
        "mode": "integrate",
        "merged": True,
        "audit_ok": True,
        "debt": None,
        "ts": "2026-10-30T19:00:00+00:00",
    }
    return {**base, **over}


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"audit_ok": False}, "audit_ok"),
        ({"schema": 2}, "schema"),
        ({"tip": "e" * 40}, "tip"),
        ({"mode": "manual"}, "modo"),
        ({"head_after": ""}, "head_after"),
    ],
)
def test_receipt_problem_rejects_each_invalid_receipt(tmp_path, override, fragment):
    tip = "a" * 40
    assert it.receipt_problem(tmp_path, tip) == "sin recibo"
    it.write_receipt(tmp_path, _receipt(tip))
    assert it.receipt_problem(tmp_path, tip) is None  # control positivo
    it.receipt_path(tmp_path, tip).write_text(
        json.dumps(_receipt(tip, **override)), encoding="utf-8"
    )
    assert fragment in (it.receipt_problem(tmp_path, tip) or "")


def test_unreadable_receipt_is_a_problem_not_a_crash(tmp_path):
    tip = "a" * 40
    path = it.receipt_path(tmp_path, tip)
    path.parent.mkdir(parents=True)
    path.write_text("{no json", encoding="utf-8")
    assert "ilegible" in (it.receipt_problem(tmp_path, tip) or "")


def test_required_receipt_shas_skips_repo_destino_and_dedups():
    text = (
        f"{'a' * 40} code phase=MANAGER_REVIEW delivery_authority=repo_motor "
        "source=session-close\n"
        f"{'b' * 40} code delivery_authority=repo_destino source=session-close\n"
        "# comentario\n"
        f"{'a' * 40} code\n"
        f"{'c' * 40} code\n"
    )
    assert it.required_receipt_shas(text) == ["a" * 40, "c" * 40]


def test_verify_receipts_exempts_declared_debt_and_demands_the_rest(
    tmp_path, monkeypatch
):
    debt, other = "d" * 40, "f" * 40
    monkeypatch.setitem(cle.HISTORIC_LOOP_DEBT, debt, "WOT-2026-143b")
    text = f"{debt} code\n{other} code\n"
    problems, notes = it.verify_receipts(tmp_path, text, None)
    assert problems == [f"{other}: sin recibo"]
    assert any("143b" in n for n in notes)
    it.write_receipt(tmp_path, _receipt(other))
    problems, _notes = it.verify_receipts(tmp_path, text, None)
    assert problems == []


def test_verify_receipts_rejects_a_tip_that_left_the_motor_head(tmp_path):
    w = _world(
        tmp_path
    )  # el candidato NO esta integrado: su tip no es ancestro del HEAD
    it.write_receipt(w.destino, _receipt(w.tip))
    problems, _notes = it.verify_receipts(w.destino, f"{w.tip} code\n", w.motor)
    assert problems and "ancestro" in problems[0]
    _git(w.motor, "merge", "--ff-only", "candidate")
    assert it.verify_receipts(w.destino, f"{w.tip} code\n", w.motor)[0] == []


# el paso de cierre - barrera
def _step(project_root: Path, targets: Path, dry_run: bool = False) -> StepResult:
    return gates.step_integration_receipts(
        project_root, dry_run, targets_path=targets, step_result_cls=StepResult
    )


def test_step_fails_blocking_when_a_target_has_no_receipt_and_passes_with_it(tmp_path):
    """M2: sin el paso, un objetivo sin recibo cruza el cierre en silencio."""
    targets = tmp_path / "loop_execution_targets.txt"
    tip = "a" * 40
    targets.write_text(f"{tip} code source=session-close\n", encoding="utf-8")
    red = _step(tmp_path, targets)
    assert red.status == "FAIL" and red.blocking is True
    assert tip in red.detail and "integrate_ticket.py" in red.detail
    it.write_receipt(tmp_path, _receipt(tip))
    green = _step(tmp_path, targets)
    assert green.status == "PASS" and green.blocking is True, green.detail


def test_step_exempts_declared_debt_and_names_it(tmp_path, monkeypatch):
    sha = "d" * 40
    monkeypatch.setitem(cle.HISTORIC_LOOP_DEBT, sha, "WOT-2026-143b")
    targets = tmp_path / "t.txt"
    targets.write_text(f"{sha} code\n", encoding="utf-8")
    res = _step(tmp_path, targets)
    assert res.status == "PASS" and "WOT-2026-143b" in res.detail, res.detail


def test_step_skips_in_dry_run_and_without_targets_but_never_reads_an_unreadable_file_as_empty(
    tmp_path,
):
    targets = tmp_path / "t.txt"
    assert _step(tmp_path, targets).status == "SKIP"
    assert _step(tmp_path, targets).blocking is False
    targets.write_text(f"{'a' * 40} code\n", encoding="utf-8")
    assert _step(tmp_path, targets, dry_run=True).status == "SKIP"
    broken = tmp_path / "dir_instead_of_file"
    broken.mkdir()
    res = _step(tmp_path, broken)
    assert res.status == "FAIL" and res.blocking is True


def test_closeout_wrapper_reads_the_targets_file_the_writer_writes(tmp_path):
    from scripts import session_closeout as sc

    targets = tmp_path / sc.LOOP_EXECUTION_TARGETS_REL
    targets.parent.mkdir(parents=True)
    tip = "a" * 40
    targets.write_text(f"{tip} code source=session-close\n", encoding="utf-8")
    assert sc._step_integration_receipts(tmp_path, False).status == "FAIL"
    it.write_receipt(tmp_path, _receipt(tip))
    assert sc._step_integration_receipts(tmp_path, False).status == "PASS"
    assert sc._step_integration_receipts(tmp_path, True).status == "SKIP"
