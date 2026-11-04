"""Tests focales del clasificador mecanico de revision proporcional."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.flight import review_level


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "review_level.py"
REAL_BACKLOG_ROW = (
    "| Media | WOT-2026-157b | REVISION PROPORCIONAL AL RIESGO: CRITERIO "
    "MECANICO DEL NIVEL DE REVISION (COMPLETA O DELTA) Y CRITERIO DE PARADA. "
    "Files Likely Touched: .agent/rules/common/revision_proporcional.md, "
    "scripts/flight/review_level.py, tests/unit/test_review_level.py. "
    "deliverable_type: mixed | motor/lentes-vuelo | pending | - | CO-29 |"
)


def _git_tracked(path: str) -> str:
    """Comprueba que el ejemplo pertenece al repo real y devuelve su ruta."""
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _git(repo: Path, *args: str) -> str:
    """Ejecuta un comando Git en un repositorio temporal de prueba."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _temp_repo(tmp_path: Path) -> Path:
    """Crea un repositorio Git temporal con identidad local determinista."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Review Level Tests")
    return repo


def _commit(repo: Path, message: str) -> str:
    """Registra todos los cambios del fixture y devuelve el SHA."""
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _backlog(tmp_path: Path, *, risk: bool = False, duplicate: bool = False) -> Path:
    """Escribe una ficha mínima con la forma real de una fila de backlog."""
    token = " [RIESGO: alto]" if risk else ""
    row = f"| Media | WOT-2026-157b | cambio{token} |"
    content = row + ("\n" + row if duplicate else "")
    path = tmp_path / "backlog.md"
    path.write_text(content, encoding="utf-8")
    return path


def _cli(
    repo: Path,
    base: str,
    sha: str,
    *,
    backlog: Path | None = None,
    ticket: str | None = "WOT-2026-157b",
    brief: Path | None = None,
    reviewed_sha: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta la CLI real contra el repositorio temporal indicado."""
    args = [
        sys.executable,
        str(SCRIPT),
        "--base",
        base,
        "--sha",
        sha,
        "--repo",
        str(repo),
    ]
    if reviewed_sha is not None:
        args.extend(["--reviewed-sha", reviewed_sha])
    if backlog is not None:
        args.extend(["--backlog", str(backlog)])
    if ticket is not None:
        args.extend(["--ticket", ticket])
    if brief is not None:
        args.extend(["--brief", str(brief)])
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)


def _sibling_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Crea dos commits hermanos con árboles distintos, como un amend real."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("parent\n", encoding="utf-8")
    parent = _commit(repo, "parent")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "first.py").write_text("one\n", encoding="utf-8")
    reviewed = _commit(repo, "reviewed")
    _git(repo, "reset", "--hard", "-q", parent)
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "second.py").write_text("two\n", encoding="utf-8")
    sha = _commit(repo, "amended")
    return repo, parent, reviewed, sha


def _large_parent_sibling_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Crea siblings cuyo diff revisado es pequeño pero cuyo base es grande."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src").mkdir()
    (repo / "src" / "ordinary.py").write_text(
        "\n".join(f"line_{i}" for i in range(60)) + "\n", encoding="utf-8"
    )
    parent = _commit(repo, "large parent")
    (repo / "src" / "ordinary.py").write_text(
        "\n".join(["reviewed"] + [f"line_{i}" for i in range(1, 60)]) + "\n",
        encoding="utf-8",
    )
    reviewed = _commit(repo, "reviewed")
    _git(repo, "reset", "--hard", "-q", parent)
    (repo / "src" / "ordinary.py").write_text(
        "\n".join(["amended"] + [f"line_{i}" for i in range(1, 60)]) + "\n",
        encoding="utf-8",
    )
    sha = _commit(repo, "amended")
    return repo, base, reviewed, sha


@pytest.mark.parametrize(
    ("family", "path"),
    [
        ("consent", ".agent/rules/common/consentimiento_accion_clase_b.md"),
        ("guards", "scripts/check_guard_wiring.py"),
        ("hooks", ".agent/config/hooks_config.json"),
        ("ruleset", ".agent/rules/common/flight_push_policy.md"),
        ("lenses", "scripts/ensemble_dispatch.py"),
        ("integration", "scripts/flight/integrate_ticket.py"),
        ("state", ".agent/runtime/events/README.md"),
        ("push-sync-delete", "scripts/check_push_authority.py"),
        ("closeout", "scripts/check_closeout_reconciliation.py"),
    ],
)
def test_high_risk_family_examples_are_real_and_match(family: str, path: str):
    """Cada familia probada usa un fichero versionado y cae en su propio glob."""
    assert _git_tracked(path) == path
    assert review_level.high_risk_family(path) == family


def test_workspace_backlog_family_is_declared_but_not_fabricated():
    """El backlog vive en el workspace destino, no como fichero versionado del motor."""
    assert (
        review_level.high_risk_family(".agent/collaboration/backlog.md")
        == "backlog-flt"
    )


def test_classifier_surfaces_are_high_risk_before_they_are_tracked():
    """Las dos rutas nuevas se clasifican como completas desde su primer diff."""
    assert (
        review_level.high_risk_family("scripts/flight/review_level.py") == "classifier"
    )
    assert (
        review_level.high_risk_family(".agent/rules/common/revision_proporcional.md")
        == "classifier"
    )


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ([], "completo"),
        (["tests/unit/test_review_level.py"], "delta"),
        (["docs/protocol/example.md"], "delta"),
        (["scripts/example.py"], "delta"),
    ],
)
def test_classification_boundaries(changed: list[str], expected: str):
    """Solo tests/docs y produccion no sensible menor al umbral dan delta."""
    result = review_level.classify_paths(
        changed,
        production_lines=10 if changed == ["scripts/example.py"] else 0,
        ficha_high_risk=False,
        diff_empty=False,
    )
    assert result.level == expected
    assert result.rc == (2 if not changed else 0)


@pytest.mark.parametrize("lines", [49, 50, 51])
def test_production_threshold_is_inclusive(lines: int):
    """La frontera provisional decide delta solo por debajo de 50."""
    result = review_level.classify_paths(
        ["scripts/ordinary.py"],
        production_lines=lines,
        ficha_high_risk=False,
        diff_empty=False,
    )
    assert result.level == ("delta" if lines == 49 else "completo")


@pytest.mark.parametrize(
    "path", ["scripts/ordinary.py", "scripts/ordinary.ps1", "scripts/ordinary.sh"]
)
def test_production_counter_includes_supported_script_extensions(path: str):
    """La definición de producción incluye Python, PowerShell y shell."""
    assert review_level._is_production(path) is True


def test_small_change_inside_high_risk_glob_is_complete():
    """Un cambio de una linea en un glob de riesgo nunca se abarata."""
    result = review_level.classify_paths(
        ["scripts/check_guard_wiring.py"],
        production_lines=1,
        ficha_high_risk=False,
        diff_empty=False,
    )
    assert result.level == "completo"


def test_previous_complete_does_not_drop_without_reason():
    """La monotonicidad conserva completo cuando no hay motivo de bajada."""
    result = review_level.apply_previous_level(
        "delta", previous_level="completo", lower_reason=""
    )
    assert result.level == "completo"
    assert "nivel-no-baja-sin-motivo" in result.reasons


def test_previous_complete_can_drop_with_nonblank_reason():
    """Un motivo no vacio permite la bajada explícita a delta."""
    result = review_level.apply_previous_level(
        "delta", previous_level="completo", lower_reason="ronda previa ya absorbida"
    )
    assert result.level == "delta"
    assert result.reasons == ("bajada-con-motivo: ronda previa ya absorbida",)


@pytest.mark.parametrize("reason", ["", "   "])
def test_blank_lower_reason_does_not_drop(reason: str):
    """El motivo vacio o de espacios no satisface la excepción."""
    result = review_level.apply_previous_level(
        "delta", previous_level="completo", lower_reason=reason
    )
    assert result.level == "completo"


def test_invalid_previous_level_is_fail_closed():
    """Un nivel anterior desconocido produce completo y rc 2."""
    result = review_level.apply_previous_level(
        "delta", previous_level="COMPLETA", lower_reason="motivo"
    )
    assert result.level == "completo"
    assert result.rc == 2


def test_empty_range_is_fail_closed():
    """Un diff sin rutas no puede autorizar una ronda delta."""
    result = review_level.classify_paths(
        [], production_lines=0, ficha_high_risk=False, diff_empty=True
    )
    assert result.level == "completo"
    assert result.rc == 2


def test_high_risk_row_is_parsed_from_real_backlog_shape(tmp_path: Path):
    """El parser busca una fila Media por ticket y acepta el token inline."""
    backlog = tmp_path / "backlog.md"
    backlog.write_text(
        REAL_BACKLOG_ROW.replace("CRITERIO ", "[RIESGO: alto] CRITERIO "),
        encoding="utf-8",
    )
    parsed = review_level.read_ticket_risk(backlog, "WOT-2026-157b")
    assert parsed.high_risk is True
    assert parsed.rc == 0


@pytest.mark.parametrize(
    "content", ["", "| Media | WOT-2026-157b | uno\n| Media | WOT-2026-157b | dos"]
)
def test_missing_or_duplicate_ticket_row_is_fail_closed(tmp_path: Path, content: str):
    """Fila ausente o duplicada imprime completo con rc 2."""
    backlog = tmp_path / "backlog.md"
    backlog.write_text(content, encoding="utf-8")
    parsed = review_level.read_ticket_risk(backlog, "WOT-2026-157b")
    assert parsed.high_risk is False
    assert parsed.rc == 2


def test_reviewed_sha_uses_tree_diff_for_sibling_amends(tmp_path: Path):
    """La comparación reviewed..sha funciona aunque reviewed no sea ancestro."""
    repo, parent, reviewed, sha = _sibling_repo(tmp_path)
    assert _git(repo, "merge-base", reviewed, sha) == parent
    assert review_level.diff_paths(repo, reviewed, sha) == [
        "scripts/first.py",
        "scripts/second.py",
    ]


def test_cli_reviewed_sha_uses_sibling_tree_diff(tmp_path: Path):
    """La CLI aplica reviewed-sha al diff de arboles, no al historial."""
    repo, base, reviewed, sha = _large_parent_sibling_repo(tmp_path)
    result = _cli(
        repo,
        base,
        sha,
        backlog=_backlog(tmp_path),
        reviewed_sha=reviewed,
    )
    assert result.returncode == 0
    assert "NIVEL=delta" in result.stdout


def test_cli_invalid_previous_level_prints_complete_and_rc2(tmp_path: Path):
    """La interfaz conserva la salida fail-closed incluso con error de entrada."""
    backlog = tmp_path / "backlog.md"
    backlog.write_text(REAL_BACKLOG_ROW, encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base",
            "HEAD~1",
            "--sha",
            "HEAD",
            "--backlog",
            str(backlog),
            "--ticket",
            "WOT-2026-157b",
            "--prev-level",
            "desconocido",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "NIVEL=completo" in completed.stdout


def test_cli_ficha_risk_is_end_to_end_and_local_to_its_row(tmp_path: Path):
    """El token de riesgo sube solo en la fila del ticket seleccionado."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "ordinary.py").write_text("one\n", encoding="utf-8")
    sha = _commit(repo, "small change")
    high = _cli(repo, base, sha, backlog=_backlog(tmp_path, risk=True))
    low = _cli(repo, base, sha, backlog=_backlog(tmp_path, risk=False))
    other = tmp_path / "other.md"
    other.write_text(
        "| Media | WOT-2026-999x | cambio [RIESGO: alto] |\n"
        "| Media | WOT-2026-157b | cambio |\n",
        encoding="utf-8",
    )
    other_row = _cli(repo, base, sha, backlog=other)
    assert high.returncode == 0 and "NIVEL=completo" in high.stdout
    assert low.returncode == 0 and "NIVEL=delta" in low.stdout
    assert other_row.returncode == 0 and "NIVEL=delta" in other_row.stdout


def test_cli_only_tests_docs_over_50_real_lines_stays_delta(tmp_path: Path):
    """El contador real excluye tests aunque el diff supere 50 líneas."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "tests").mkdir()
    (repo / "tests" / "large_test.py").write_text(
        "\n".join(f"line_{i}" for i in range(60)) + "\n", encoding="utf-8"
    )
    sha = _commit(repo, "tests only")
    result = _cli(repo, base, sha, backlog=_backlog(tmp_path))
    assert result.returncode == 0
    assert "NIVEL=delta" in result.stdout
    assert review_level.production_line_count(repo, base, sha) == 0


@pytest.mark.parametrize(
    "kind",
    ["ticket-ausente", "ficha-ausente", "ticket-duplicado", "backlog-inexistente"],
)
def test_cli_fail_closed_input_variants(tmp_path: Path, kind: str):
    """Las entradas ausentes, duplicadas o ilegibles siempre cierran completo."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "ordinary.py").write_text("one\n", encoding="utf-8")
    sha = _commit(repo, "small change")
    if kind == "ticket-ausente":
        result = _cli(repo, base, sha, backlog=_backlog(tmp_path), ticket=None)
    elif kind == "ficha-ausente":
        result = _cli(repo, base, sha, backlog=None)
    elif kind == "ticket-duplicado":
        result = _cli(repo, base, sha, backlog=_backlog(tmp_path, duplicate=True))
    else:
        result = _cli(
            repo,
            base,
            sha,
            backlog=tmp_path / "missing-backlog.md",
        )
    assert result.returncode == 2
    assert "NIVEL=completo" in result.stdout


def test_cli_review_level_error_is_fail_closed(tmp_path: Path):
    """La rama de ReviewLevelError convierte Git ilegible en completo/rc2."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    result = _cli(repo, "missing-base", base, backlog=_backlog(tmp_path))
    assert result.returncode == 2
    assert "NIVEL=completo" in result.stdout


def test_cli_brief_risk_and_missing_marker(tmp_path: Path):
    """El brief alto sube; la ausencia de su marca no sube."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "ordinary.py").write_text("one\n", encoding="utf-8")
    sha = _commit(repo, "small change")
    high = tmp_path / "high.md"
    high.write_text("RISK_LEVEL: high\n", encoding="utf-8")
    absent = tmp_path / "absent.md"
    absent.write_text("RISK_LEVEL: medium\n", encoding="utf-8")
    assert "NIVEL=completo" in _cli(repo, base, sha, brief=high).stdout
    assert "NIVEL=delta" in _cli(repo, base, sha, brief=absent).stdout


def test_cli_brief_missing_is_fail_closed(tmp_path: Path):
    """Un brief ilegible da completo con rc2."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "ordinary.py").write_text("one\n", encoding="utf-8")
    sha = _commit(repo, "small change")
    result = _cli(repo, base, sha, brief=tmp_path / "missing-brief.md")
    assert result.returncode == 2
    assert "NIVEL=completo" in result.stdout


def test_cli_unicode_high_risk_path_is_not_quoted_away(tmp_path: Path):
    """Un nombre Unicode que casa con glob sigue siendo completo por CLI."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "check_á.py").write_text("one\n", encoding="utf-8")
    sha = _commit(repo, "unicode guard")
    result = _cli(repo, base, sha, backlog=_backlog(tmp_path))
    assert result.returncode == 0
    assert "NIVEL=completo" in result.stdout


def test_cli_unicode_production_path_counts_60_lines(tmp_path: Path):
    """Un .py Unicode fuera de globs cuenta 60 líneas y sube a completo."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src").mkdir()
    (repo / "src" / "á.py").write_text(
        "\n".join(f"line_{i}" for i in range(60)) + "\n", encoding="utf-8"
    )
    sha = _commit(repo, "unicode production")
    result = _cli(repo, base, sha, backlog=_backlog(tmp_path))
    assert result.returncode == 0
    assert "NIVEL=completo" in result.stdout


def test_cli_binary_stats_are_fail_closed(tmp_path: Path):
    """Un diff binario no se interpreta como cero líneas."""
    repo = _temp_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "asset.bin").write_bytes(b"one\x00")
    base = _commit(repo, "base")
    (repo / "asset.bin").write_bytes(b"two\x00")
    sha = _commit(repo, "binary change")
    result = _cli(repo, base, sha, backlog=_backlog(tmp_path))
    assert result.returncode == 2
    assert "NIVEL=completo" in result.stdout


def test_path_normalisation_accepts_windows_and_dot_prefixes():
    """Los paths Windows y ./ conservan la clasificación de sus globs."""
    assert review_level.high_risk_family(r".\scripts\check_guard_wiring.py") == "guards"
    assert review_level.high_risk_family("./scripts/check_guard_wiring.py") == "guards"


def test_numstat_z_preserves_path_after_a_tab(monkeypatch: pytest.MonkeyPatch):
    """El tercer campo numstat conserva íntegra una ruta con tabulador."""
    output = "60\t0\tsrc/a\tdocs/modulo.py\0"
    monkeypatch.setattr(
        review_level,
        "_run_git",
        lambda repo, args: subprocess.CompletedProcess(
            ["git"], 0, stdout=output, stderr=""
        ),
    )
    assert review_level.production_line_count(Path("."), "left", "right") == 60


def test_name_only_z_preserves_path_after_a_tab(monkeypatch: pytest.MonkeyPatch):
    """El parser de nombres también conserva todos los bytes del path."""
    output = "src/a\tdocs/modulo.py\0"
    monkeypatch.setattr(
        review_level,
        "_run_git",
        lambda repo, args: subprocess.CompletedProcess(
            ["git"], 0, stdout=output, stderr=""
        ),
    )
    assert review_level.diff_paths(Path("."), "left", "right") == [
        "src/a\tdocs/modulo.py"
    ]


def test_cli_unexpected_exception_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Una excepción inesperada conserva NIVEL completo y rc 2."""
    monkeypatch.setattr(
        review_level,
        "diff_paths",
        lambda repo, left, right: (_ for _ in ()).throw(ValueError("inesperado")),
    )
    rc = review_level.main(
        [
            "--base",
            "base",
            "--sha",
            "sha",
            "--backlog",
            str(_backlog(tmp_path)),
            "--ticket",
            "WOT-2026-157b",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "NIVEL=completo" in captured.out
    assert "RAZON=error-inesperado" in captured.out


@pytest.mark.parametrize(
    "args",
    [["--sha", "HEAD"], ["--base", "HEAD", "--sha", "HEAD", "--unknown"]],
)
def test_cli_argparse_errors_print_complete(args: list[str]):
    """Errores de argparse mantienen la salida fail-closed del contrato."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "NIVEL=completo" in result.stdout
    assert "RAZON=argumentos-invalidos" in result.stdout
