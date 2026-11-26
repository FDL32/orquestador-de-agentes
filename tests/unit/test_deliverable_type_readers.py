"""WOT-2026-074e: lectores de ``deliverable_type`` acotados a Metadata.

El contrato espejo es ``tests/unit/test_ticket_authority_readers.py``. Estas
pruebas fuerzan que la prosa anterior o posterior a ``## Metadata`` no pueda
decidir el tipo de entregable ni relajar el gate de la suite canónica.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load(name: str):
    """Load one production script by its repository path.

    Before: ``name`` identifies a Python script under ``scripts/``.
    During: imports the module through its file spec and registers it before
        execution so annotations and sibling imports resolve consistently.
    After: returns the loaded module or raises an actionable import error.
    """
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"modulo no cargable: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_pg = _load("pre_handoff_guard")
_erp = _load("export_review_packet")
_wpa = _load("work_plan_authority")

TRAP = "prosa trampa: deliverable_type: documentation debe quedar fuera de Metadata."


def _plan(
    dtype: str | None = "code",
    *,
    prose: str = "",
    prelude: str = "",
    section: bool = True,
    field_line: str | None = None,
) -> str:
    """Build a work plan fixture with controlled Metadata placement.

    Before: ``dtype`` is the declared value, or ``None`` for an absent field.
    During: places optional prelude/prose outside Metadata and supports the
        three field spellings exercised by the contract.
    After: returns complete plan text suitable for every reader under test.
    """
    metadata = "## Metadata\n- **ID:** WOT-2026-TEST\n- **Estado:** APPROVED\n"
    if dtype is not None:
        metadata += field_line or f"- **deliverable_type:** {dtype}"
        metadata += "\n"
    body = "# Plan de Prueba\n\n"
    if prelude:
        body += f"## Contexto previo\n{prelude}\n\n"
    if section:
        body += metadata + "\n"
    if prose:
        body += f"## Contexto\n{prose}\n"
    return body


def _read_pg(content: str, _tmp: Path) -> str:
    return _pg._read_deliverable_type_from_content(content)


def _read_erp(content: str, _tmp: Path) -> str:
    return _erp._plan_deliverable_type(content)


def _read_sco(content: str, tmp: Path) -> str:
    """Read the observation reader through its real ticket-extraction path.

    Before: ``tmp`` is an isolated AGENT_DIR and ``content`` is a work plan.
    During: redirects the module's AGENT_DIR and extracts the completion
        observation that contains the resolved type.
    After: returns the type encoded in that observation signal.
    """
    import scripts.session_close_observations as sco

    collaboration = tmp / "collaboration"
    collaboration.mkdir()
    plan = content.replace("WOT-2026-TEST", "WOT-2026-074e")
    (collaboration / "work_plan.md").write_text(plan, encoding="utf-8")
    old_agent_dir = sco.AGENT_DIR
    sco.AGENT_DIR = tmp
    try:
        candidates = sco.extract_candidates_from_ticket("WOT-2026-074e")
    finally:
        sco.AGENT_DIR = old_agent_dir
    completion = next(
        candidate
        for candidate in candidates
        if candidate.get("topic") == "ticket-completion"
    )
    return completion["signal"].split("deliverable_type=", 1)[1].rstrip(")")


READERS = pytest.mark.parametrize(
    "reader",
    [_read_pg, _read_erp, _read_sco],
    ids=["pre_handoff_guard", "export_review_packet", "session_close_obs"],
)


@READERS
def test_metadata_code_manda_sobre_prosa_posterior(reader, tmp_path):
    """Metadata ``code`` wins over a later prose trap for every reader."""
    assert reader(_plan("code", prose=TRAP), tmp_path) == "code"


@READERS
def test_metadata_documentation_mantiene_eficacia(reader, tmp_path):
    """Metadata ``documentation`` wins over prose claiming ``code``."""
    prose = TRAP.replace("documentation", "code")
    assert reader(_plan("documentation", prose=prose), tmp_path) == "documentation"


@READERS
def test_prosa_anterior_a_metadata_no_decide(reader, tmp_path):
    """A trap before Metadata cannot shadow the later declaration."""
    assert reader(_plan("code", prose=TRAP, prelude=TRAP), tmp_path) == "code"


def test_resolve_motivos_exactos():
    """The resolver distinguishes field, missing field, and missing section."""
    assert _wpa.resolve_deliverable_type_from_content(_plan("analysis")) == (
        "analysis",
        "metadata_field",
    )
    assert _wpa.resolve_deliverable_type_from_content(_plan(None, prose=TRAP)) == (
        "code",
        "no_field_in_metadata",
    )
    assert _wpa.resolve_deliverable_type_from_content("# Plan\n\n" + TRAP) == (
        "code",
        "no_metadata_section",
    )


def test_compuesto_invalido_y_normalizacion():
    """Composite, invalid, and mixed-case values follow the vocabulary contract."""
    assert _wpa.resolve_deliverable_type_from_content(_plan("code+documentation")) == (
        "mixed",
        "metadata_field",
    )
    assert _wpa.resolve_deliverable_type_from_content(_plan("banana")) == (
        "code",
        "no_field_in_metadata",
    )
    assert _wpa.read_deliverable_type(_plan("Code")) == "code"
    assert _wpa.read_deliverable_type(_plan("DOCUMENTATION")) == "documentation"


def test_formas_de_linea_en_metadata():
    """Bold bullet, plain, and bold non-bullet field lines are all accepted."""
    assert (
        _wpa.read_deliverable_type(
            _plan("documentation", field_line="- **deliverable_type:** documentation")
        )
        == "documentation"
    )
    assert (
        _wpa.read_deliverable_type(
            _plan("research", field_line="deliverable_type: research")
        )
        == "research"
    )
    assert (
        _wpa.read_deliverable_type(
            _plan("analysis", field_line="**deliverable_type:** analysis")
        )
        == "analysis"
    )


def _write_active_plan(root: Path, content: str) -> None:
    """Write an isolated active plan below ``root``."""
    collaboration = root / ".agent" / "collaboration"
    collaboration.mkdir(parents=True, exist_ok=True)
    (collaboration / "work_plan.md").write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (_plan("analysis", prose=TRAP), ("analysis", "metadata_field")),
        (_plan(None, prose=TRAP), ("code", "no_field_in_metadata")),
        ("# Plan\n\n" + TRAP, ("code", "no_metadata_section")),
        (None, ("code", "work_plan_unreadable")),
    ],
    ids=["campo", "sin_campo", "sin_seccion", "plan_ausente"],
)
def test_plan_activo_resuelve_valor_y_motivo(tmp_path, content, expected):
    """The active-plan resolver returns its value and named fallback reason."""
    if content is not None:
        _write_active_plan(tmp_path, content)
    assert _pg.resolve_deliverable_type_from_active_plan(tmp_path) == expected


def _init_git_repo(repo: Path) -> str:
    """Create a minimal repository and return its committed HEAD."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Test Repo", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_last_run(repo: Path, head: str) -> None:
    """Write the minimum fresh-green canonical-suite artifact."""
    runtime = repo / ".agent" / "runtime" / "pytest-safe"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "last-run.json").write_text(
        json.dumps(
            {
                "status": "finished",
                "exit_code": 0,
                "tested_commit_sha": head,
                "level": "all",
                "args_mode": "default_discovery",
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("content", "expected_type", "expected_reason"),
    [
        (_plan(None, prose=TRAP), "code", "no_field_in_metadata"),
        (_plan("documentation", prose=TRAP), "documentation", "metadata_field"),
        (None, "code", "work_plan_unreadable"),
    ],
    ids=["sin_campo", "campo_declarado", "plan_ausente"],
)
def test_sello_de_preflight_closeout_nombra_el_motivo(
    monkeypatch, tmp_path, content, expected_type, expected_reason
):
    """Preflight seals the REAL resolver reason, not a constant (3 reasons)."""
    pc = _load("preflight_closeout")
    if content is not None:
        _write_active_plan(tmp_path, content)

    monkeypatch.setattr(
        _pg,
        "run_guard",
        lambda root, ticket, motor_root=None: {
            "valid": True,
            "dirty_tree": False,
            "missing_checkpoint": False,
            "checkpoint_misaligned": False,
            "dirty_files": [],
        },
    )
    monkeypatch.setattr(
        _pg,
        "assert_canonical_suite_green",
        lambda root, dtype: (
            True,
            {"canonical_suite_required": True, "reason": "fresh_green"},
        ),
    )
    motor = tmp_path / "motor"
    motor.mkdir()
    report = pc.run_preflight(
        project_root=tmp_path,
        ticket_id="WOT-2026-074e",
        motor_root=motor,
    )
    assert report["deliverable_type"] == expected_type
    assert report["deliverable_type_reason"] == expected_reason
    assert expected_reason in pc._render_human(report)


@pytest.mark.parametrize(
    "value",
    [
        "documentation_and_code",
        "documentation, code",
        "documentation and code",
        "documentation/code",
        "code (no documentation)",
    ],
)
def test_valor_ambiguo_nunca_relaja_la_suite(value):
    """A value naming SEVERAL vocabulary types is `mixed` (suite required).

    Regression of the lens finding: a greedy prefix match resolved
    `documentation, code` to `documentation` and skipped the canonical suite.
    """
    plan = _plan(value)
    assert _wpa.resolve_deliverable_type_from_content(plan) == (
        "mixed",
        "metadata_field",
    )
    assert _pg._read_deliverable_type_from_content(plan) == "mixed"


@pytest.mark.parametrize("value", ["`documentation`", '"documentation"'])
def test_valor_con_backticks_o_comillas_se_resuelve(value):
    """Markdown/quote decoration around a single value does not hide it."""
    assert _wpa.resolve_deliverable_type_from_content(_plan(value)) == (
        "documentation",
        "metadata_field",
    )


def test_mixed_literal_en_metadata_es_valido():
    """`mixed` declared directly (no `+`) is a valid vocabulary member."""
    assert _wpa.resolve_deliverable_type_from_content(_plan("mixed")) == (
        "mixed",
        "metadata_field",
    )


def test_plan_activo_no_decodificable_es_work_plan_unreadable(tmp_path):
    """Undecodable bytes (UnicodeDecodeError is not OSError) fail closed to code."""
    collaboration = tmp_path / ".agent" / "collaboration"
    collaboration.mkdir(parents=True)
    (collaboration / "work_plan.md").write_bytes(
        b"## Metadata\n- **deliverable_type:** documentation\n\xff\xfe\n"
    )
    assert _pg.resolve_deliverable_type_from_active_plan(tmp_path) == (
        "code",
        "work_plan_unreadable",
    )


def test_session_close_conserva_unknown_sin_campo(tmp_path):
    """Without a Metadata field the observer keeps the literal `unknown`."""
    assert _read_sco(_plan(None, prose=TRAP), tmp_path) == "unknown"


def test_plan_activo_alimenta_el_gate_canonico_punta_a_punta(tmp_path):
    """Active Metadata controls required-suite enforcement end to end."""
    code_root = tmp_path / "code"
    code_head = _init_git_repo(code_root)
    _write_active_plan(
        code_root,
        _plan("code", prose="la prosa contradice con deliverable_type: documentation"),
    )
    _write_last_run(code_root, code_head)
    code_type = _pg._read_deliverable_type_from_active_plan(code_root)
    code_ok, code_diag = _pg.assert_canonical_suite_green(code_root, code_type)
    assert code_type == "code"
    assert code_ok is True
    assert code_diag["canonical_suite_required"] is True

    docs_root = tmp_path / "docs"
    docs_head = _init_git_repo(docs_root)
    _write_active_plan(
        docs_root,
        _plan("documentation", prose="la prosa contradice con deliverable_type: code"),
    )
    _write_last_run(docs_root, docs_head)
    docs_type = _pg._read_deliverable_type_from_active_plan(docs_root)
    docs_ok, docs_diag = _pg.assert_canonical_suite_green(docs_root, docs_type)
    assert docs_type == "documentation"
    assert docs_ok is True
    assert docs_diag["canonical_suite_required"] is False
    assert docs_diag["reason"] == "deliverable_type_skip"
