"""Barrier tests de scripts/check_cuspide_growth_and_drift.py.

Cubre los 15 casos del contrato del Manager (Seccion 9 de
`gate_impl_manager_plan.md`). Cada assert mide una transicion real sobre un
repo git temporal: exit code, stderr/stdout o artefacto de telemetria.

Hermeticidad (vector git CEM): cada fixture hace `git init` en SU raiz y
`_init_repo` verifica que `git rev-parse --show-toplevel` resuelve a esa misma
raiz. Si el walk-up alcanzara el repo real, el test aborta.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_cuspide_growth_and_drift.py"
_GIT = shutil.which("git") or "git"


def _load(name: str, path: Path):
    """Carga un modulo por ruta sin depender del cwd ni del sys.path del repo."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cgd = _load("check_cuspide_growth_and_drift", _SCRIPT)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(root: Path) -> None:
    """Inicializa un repo temporal y prueba que el toplevel es ESA raiz."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "core.autocrlf", "false")
    probe = _git(root, "rev-parse", "--show-toplevel")
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).resolve() == root.resolve(), (
        "walk-up de git alcanzo OTRO repo: el test NO es hermetico"
    )


def _write(root: Path, rel: str, content: str | bytes) -> Path:
    """Escribe con bytes para no introducir CRLF por la traduccion de Python."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = content.encode("utf-8") if isinstance(content, str) else content
    path.write_bytes(raw)
    return path


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    result = _git(root, "commit", "-q", "-m", message)
    assert result.returncode == 0, result.stderr
    rev = _git(root, "rev-parse", "HEAD")
    assert rev.returncode == 0, rev.stderr
    return rev.stdout.strip()


def _seed(root: Path, agents: str, claude: str = "@AGENTS.md\n") -> str:
    """Baseline con AGENTS.md/CLAUDE.md ya commiteados (sin hooks de fixture)."""
    _write(root, "AGENTS.md", agents)
    _write(root, "CLAUDE.md", claude)
    return _commit_all(root, "baseline")


def _message(root: Path, text: str) -> Path:
    return _write(root, ".git/COMMIT_EDITMSG_TEST", text)


def _run(root: Path, phase: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--phase",
            phase,
            "--repo-root",
            str(root),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _extract_numbers(text: str) -> list[str]:
    return re.findall(
        r"(?:delta_bytes|delta_chars|ratio_codex_post|ratio_cc_post)="
        r"([+-]?[0-9.]+)",
        text,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


# ---------------------------------------------------------------- casos 1-3
def test_no_cuspide_touch_is_silent(repo: Path) -> None:
    """Caso 1: un commit de otro fichero no emite la marca del guard."""
    _seed(repo, "a" * 100)
    _write(repo, "other.txt", "x\n")
    _git(repo, "add", "other.txt")
    message = _message(repo, "touch other")

    pre = _run(repo, "pre-commit")
    assert pre.returncode == 0, pre.stderr
    assert cgd.MARKER not in pre.stdout + pre.stderr

    commit_msg = _run(repo, "commit-msg", str(message))
    assert commit_msg.returncode == 0, commit_msg.stderr
    assert cgd.MARKER not in commit_msg.stdout + commit_msg.stderr


def test_reduction_is_silent(repo: Path) -> None:
    """Caso 2: reducir ambos gates no dispara growth."""
    _seed(repo, "a" * 33000)
    _write(repo, "AGENTS.md", "a" * 32000)
    _git(repo, "add", "AGENTS.md")
    message = _message(repo, "reduce")

    for phase, extra in (("pre-commit", ()), ("commit-msg", (str(message),))):
        result = _run(repo, phase, *extra)
        assert result.returncode == 0, result.stderr
        # La reduccion no dispara growth. pre-commit puede emitir ademas el
        # WARN de drift (solo AGENTS.md tocado, capa 2 no), que no habla de
        # deltas; commit-msg es silencioso.
        assert "delta_bytes" not in result.stderr
        assert "BLOCK" not in result.stderr


def test_growth_over_ratio_blocks_without_override(repo: Path) -> None:
    """Caso 3: growth sobre-ratio sin override -> exit 1 con numeros exactos."""
    _seed(repo, "a" * 33000)
    _write(repo, "AGENTS.md", "a" * 33001)
    _git(repo, "add", "AGENTS.md")
    message = _message(repo, "grow")

    result = _run(repo, "commit-msg", str(message))
    assert result.returncode == 1, result.stderr
    assert "delta_bytes=+1" in result.stderr
    assert "ratio_codex_post=1.0071" in result.stderr


# ---------------------------------------------------------------- casos 4-6
def test_override_allows_and_post_commit_audits(repo: Path) -> None:
    """Caso 4: override valido -> permitido y exactamente 1 linea auditada."""
    _seed(repo, "a" * 33000)
    _write(repo, "AGENTS.md", "a" * 33001)
    _git(repo, "add", "AGENTS.md")
    text = (
        "grow with override\n\n"
        "GATE-OVERRIDE: cuspide_growth\n"
        "REASON: fixture override\n"
        "AFFECTED: codex_bytes\n"
    )
    message = _message(repo, text)

    commit_msg = _run(repo, "commit-msg", str(message))
    assert commit_msg.returncode == 0, commit_msg.stderr
    assert "override aceptado" in commit_msg.stderr

    assert _git(repo, "commit", "-q", "-F", str(message)).returncode == 0
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    post = _run(repo, "post-commit")
    assert post.returncode == 0, post.stderr

    audit = repo / ".agent/runtime/cuspide_growth_overrides.jsonl"
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "cuspide_override"
    assert entry["commit"] == sha
    assert entry["reason"] == "fixture override"
    assert entry["affected"] == "codex_bytes"
    assert entry["delta_bytes"] == 1
    assert entry["delta_chars"] == 1


def test_growth_within_caps_warns(repo: Path) -> None:
    """Caso 5: growth con ambos ratio_post <= 1.0 -> WARN, exit 0."""
    _seed(repo, "a" * 100)
    _write(repo, "AGENTS.md", "a" * 110)
    _git(repo, "add", "AGENTS.md")
    message = _message(repo, "small grow")

    result = _run(repo, "commit-msg", str(message))
    assert result.returncode == 0, result.stderr
    assert "WARN" in result.stderr
    assert "ratio_post" in result.stderr


@pytest.mark.parametrize(
    "text",
    [
        "grow\n\nGATE-OVERRIDE: cuspide_growth\n",
        "grow\n\nGATE-OVERRIDE: cuspide_growth\nREASON:   \n",
    ],
)
def test_override_without_reason_blocks(repo: Path, text: str) -> None:
    """Caso 6: marcador sin REASON (o vacio) no es override."""
    _seed(repo, "a" * 33000)
    _write(repo, "AGENTS.md", "a" * 33001)
    _git(repo, "add", "AGENTS.md")
    message = _message(repo, text)

    result = _run(repo, "commit-msg", str(message))
    assert result.returncode == 1, result.stderr
    assert "REASON" in result.stderr
    assert "formulario" in result.stderr


# ---------------------------------------------------------------- casos 7-10
def test_pre_commit_is_early_warning_never_blocks(repo: Path) -> None:
    """Caso 7: growth sobre-ratio en pre-commit -> exit 0 + gramatica."""
    _seed(repo, "a" * 33000)
    _write(repo, "AGENTS.md", "a" * 33001)
    _git(repo, "add", "AGENTS.md")

    result = _run(repo, "pre-commit")
    assert result.returncode == 0, result.stderr
    assert "EARLY WARNING" in result.stderr
    assert "GATE-OVERRIDE: cuspide_growth" in result.stderr
    assert "REASON:" in result.stderr


def test_pre_commit_and_commit_msg_measure_the_same_index(repo: Path) -> None:
    """Caso 8: paridad de numeros entre pre-commit y commit-msg."""
    _seed(repo, "a" * 33000)
    _write(repo, "AGENTS.md", "a" * 33001)
    _git(repo, "add", "AGENTS.md")
    message = _message(repo, "grow")

    pre = _run(repo, "pre-commit")
    commit_msg = _run(repo, "commit-msg", str(message))
    assert pre.returncode == 0
    assert commit_msg.returncode == 1
    assert _extract_numbers(pre.stderr) == _extract_numbers(commit_msg.stderr)
    assert _extract_numbers(pre.stderr), "la fase no imprimio metricas"


def test_measurement_reads_the_index_not_the_working_tree(repo: Path) -> None:
    """Caso 9: sin `git add` la medicion no cambia; tras add, si."""
    _seed(repo, "a" * 100)
    before = cgd.measure_snapshot("INDEX", repo)
    assert before.agents_bytes == 100

    _write(repo, "AGENTS.md", "a" * 200)
    unstaged = cgd.measure_snapshot("INDEX", repo)
    assert unstaged.agents_bytes == before.agents_bytes == 100

    _git(repo, "add", "AGENTS.md")
    staged = cgd.measure_snapshot("INDEX", repo)
    assert staged.agents_bytes == 200


def test_crlf_working_tree_measures_the_lf_blob(repo: Path) -> None:
    """Caso 10: CRLF en el working tree no altera el blob medido."""
    _seed(repo, "line\n")
    before = cgd.measure_snapshot("INDEX", repo)
    assert before.agents_bytes == 5

    _write(repo, "AGENTS.md", b"line\r\n")
    after = cgd.measure_snapshot("INDEX", repo)
    assert after.agents_bytes == before.agents_bytes == 5
    assert (repo / "AGENTS.md").read_bytes() == b"line\r\n"


# ---------------------------------------------------------------- casos 11-12
def test_first_commit_without_parent_is_fail_safe(tmp_path: Path) -> None:
    """Caso 11: primer commit (sin HEAD/HEAD^) no lanza traceback."""
    _init_repo(tmp_path)
    _write(tmp_path, "AGENTS.md", "a" * 100)
    _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
    _git(tmp_path, "add", "-A")

    pre = _run(tmp_path, "pre-commit")
    assert pre.returncode == 0
    assert "Traceback" not in pre.stdout + pre.stderr

    assert _git(tmp_path, "commit", "-q", "-m", "first").returncode == 0
    post = _run(tmp_path, "post-commit")
    assert post.returncode == 0
    assert "Traceback" not in post.stdout + post.stderr


def test_override_inside_a_comment_is_ignored(repo: Path) -> None:
    """Caso 12: strip_comments antes de parsear el override."""
    _seed(repo, "a" * 33000)
    _write(repo, "AGENTS.md", "a" * 33001)
    _git(repo, "add", "AGENTS.md")
    message = _message(
        repo,
        "grow\n\n# GATE-OVERRIDE: cuspide_growth\n# REASON: fake\n",
    )

    result = _run(repo, "commit-msg", str(message))
    assert result.returncode == 1, result.stderr
    assert "BLOCK" in result.stderr
    assert "formulario" not in result.stderr


# ---------------------------------------------------------------- caso 13
def test_drift_layer2_only_warns(repo: Path) -> None:
    """Caso 13a: solo capa 2 -> WARN drift, exit 0."""
    _seed(repo, "a" * 100)
    _write(repo, ".agent/rules/common/x.md", "rule\n")
    _git(repo, "add", ".agent/rules/common/x.md")

    result = _run(repo, "pre-commit")
    assert result.returncode == 0, result.stderr
    assert "WARN drift" in result.stderr
    assert ".agent/rules/common/x.md" in result.stderr


def test_drift_only_cuspide_uses_growth_path(repo: Path) -> None:
    """Caso 13b: solo cuspide -> el camino de growth decide el mensaje."""
    _seed(repo, "a" * 100)
    _write(repo, "AGENTS.md", "a" * 105)
    _git(repo, "add", "AGENTS.md")

    result = _run(repo, "pre-commit")
    assert result.returncode == 0, result.stderr
    assert "delta_bytes=+5" in result.stderr


def test_drift_both_sides_is_silent(repo: Path) -> None:
    """Caso 13c: cuspide + capa 2 juntas -> sin WARN de drift."""
    _seed(repo, "a" * 100)
    _write(repo, "AGENTS.md", "a" * 105)
    _write(repo, ".agent/rules/common/x.md", "rule\n")
    _git(repo, "add", "AGENTS.md", ".agent/rules/common/x.md")

    result = _run(repo, "pre-commit")
    assert result.returncode == 0, result.stderr
    assert "drift" not in result.stderr.lower()


# ---------------------------------------------------------------- casos 14-15
def test_import_outside_historical_regex_triggers_block(tmp_path: Path) -> None:
    """Caso 14: un import fuera de AGENTS.md se resuelve y bloquea."""
    _init_repo(tmp_path)
    _write(tmp_path, "CLAUDE.md", "@docs/protocol/x.md\n")
    _write(tmp_path, "docs/protocol/x.md", "y" * 40050)
    _commit_all(tmp_path, "baseline")

    _write(tmp_path, "docs/protocol/x.md", "y" * 40051)
    _git(tmp_path, "add", "docs/protocol/x.md")
    message = _message(tmp_path, "grow imported file")

    result = _run(tmp_path, "commit-msg", str(message))
    assert result.returncode == 1, result.stderr
    assert "delta_chars=+1" in result.stderr
    assert "ratio_cc_post=" in result.stderr


def test_guard_is_wired_by_config_and_classifier() -> None:
    """Caso 15: el guard real sale WIRED y el clasificador distingue manual."""
    run = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "check_guard_wiring.py")],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr

    data = yaml.safe_load(
        (_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    assert "post-commit" in data["default_install_hook_types"]
    hooks = {
        hook["id"]: hook for repo in data["repos"] for hook in repo.get("hooks", [])
    }
    cgw = _load("check_guard_wiring", _ROOT / "scripts" / "check_guard_wiring.py")
    ids = (
        "check-cuspide-growth-warn",
        "check-cuspide-growth-gate",
        "check-cuspide-growth-audit",
    )
    for hook_id in ids:
        hook = hooks[hook_id]
        assert cgw._hook_fires(hook, None, ["AGENTS.md"]) is True
        manual = dict(hook)
        manual["stages"] = ["manual"]
        assert cgw._hook_fires(manual, None, ["AGENTS.md"]) is False
