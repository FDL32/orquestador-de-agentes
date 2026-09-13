from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scripts import check_publication_gate as gate


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _make_repo(
    base: Path, name: str, email: str = "123+bot@users.noreply.github.com"
) -> Path:
    repo = base / name
    repo.mkdir()
    _git(repo, "init")
    # WOT-2026-019c: desactivar el gc automatico en background. Los tests que
    # crean cientos de commits en bucle (test_loose_pattern_chunks_many_revs)
    # disparan el umbral de loose objects; con gc.autoDetach=true (default POSIX)
    # el `git gc --auto` corre en background y repaqueta/poda objetos justo
    # mientras `rev-list --all`/`ls-tree` los leen -> "error: Could not read
    # <sha>" transitorio -> exit 128. Flaky solo en CI (Linux). gc.auto=0 lo cierra.
    _git(repo, "config", "gc.auto", "0")
    _git(repo, "config", "user.email", email)
    _git(repo, "config", "user.name", "Bot")
    (repo / "README.md").write_text("# limpio\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    return repo


def test_make_repo_disables_autogc(tmp_path: Path) -> None:
    """WOT-2026-019c: _make_repo debe fijar gc.auto=0 para que el gc en
    background no corra durante los tests que crean cientos de commits (evita
    la carrera con rev-list --all que da exit 128 flaky en CI). Barrera del
    mecanismo del fix; el sintoma real (la carrera) es CI-only, no reproducible
    de forma determinista en local."""
    repo = _make_repo(tmp_path, "repo_autogc")
    result = subprocess.run(
        ["git", "config", "--get", "gc.auto"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "0"


def _gitleaks_ok_mock(repo: Path) -> dict:
    return {
        "check": "gitleaks_config",
        "ok": True,
        "evidence": {"cause": None, "config_path": "<mocked>", "config_hash": "mocked"},
    }


def test_clean_repo_is_listo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "check_gitleaks_config", _gitleaks_ok_mock)
    repo = _make_repo(tmp_path, "proyecto_limpio")
    report = gate.run_gate(repo, [], ["usuarioinexistente9x"], [])
    assert report["verdict"] == "LISTO"
    assert (
        gate.main(["--repo-root", str(repo), "--pii-term", "usuarioinexistente9x"]) == 0
    )


def test_copia_folder_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "proyecto - copia")
    report = gate.run_gate(repo, [], ["x9z"], [])
    assert report["verdict"] == "BLOCKED"
    assert any(c["check"] == "name" and not c["ok"] for c in report["checks"])


def test_dirty_tree_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "proyecto_sucio")
    (repo / "wip.txt").write_text("sin commitear\n", encoding="utf-8")
    report = gate.run_gate(repo, [], ["x9z"], [])
    assert any(c["check"] == "tree_clean" and not c["ok"] for c in report["checks"])
    assert report["verdict"] == "BLOCKED"


def test_personal_metadata_email_blocks_and_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    """El check de metadata es el UNICO que caza autores/committers (classify
    solo escanea blobs). MUTATION: sin el check, el gate daria falso verde."""
    monkeypatch.setattr(gate, "check_gitleaks_config", _gitleaks_ok_mock)
    repo = _make_repo(tmp_path, "proyecto_meta", email="persona@dominioprivado.es")
    report = gate.run_gate(repo, [], ["x9z"], [])
    meta = next(c for c in report["checks"] if c["check"] == "metadata")
    assert not meta["ok"] and "persona@dominioprivado.es" in meta["evidence"]
    assert report["verdict"] == "BLOCKED"

    # MUTATION: neutralizar el check -> falso verde (demuestra la barrera)
    monkeypatch.setattr(
        gate,
        "check_metadata",
        lambda repo, allow: {"check": "metadata", "ok": True, "evidence": []},
    )
    mutated = gate.run_gate(repo, [], ["x9z"], [])
    assert mutated["verdict"] == "LISTO"


def test_dirty_sibling_blocks_unidad(tmp_path: Path, monkeypatch) -> None:
    """El caso UNIDAD original de 016m: repo limpio + hermano con PII -> BLOCKED."""
    monkeypatch.setattr(gate, "check_gitleaks_config", _gitleaks_ok_mock)
    repo = _make_repo(tmp_path, "principal")
    hermano = _make_repo(tmp_path, "hermano")
    (hermano / "leak.md").write_text(
        "ruta: C:\\Users\\pepito\\Dropbox\\datos\n", encoding="utf-8"
    )
    _git(hermano, "add", "leak.md")
    _git(hermano, "commit", "-m", "leak en el hermano")

    report = gate.run_gate(repo, [hermano], ["pepito"], [])
    assert report["verdict"] == "BLOCKED"
    assert report["siblings"][0]["ok"] is False
    # el principal por si solo esta limpio
    solo = gate.run_gate(repo, [], ["pepito"], [])
    assert solo["verdict"] == "LISTO"


def test_loose_pattern_catches_slug_variant(tmp_path: Path) -> None:
    """El patron laxo caza la forma slug Users-term que un scan de rutas no ve."""
    repo = _make_repo(tmp_path, "proyecto_slug")
    (repo / "log.md").write_text(
        "sesion: c--Users-pepito-Proyectos\n", encoding="utf-8"
    )
    _git(repo, "add", "log.md")
    _git(repo, "commit", "-m", "slug")
    report = gate.run_gate(repo, [], ["pepito"], [])
    loose = next(c for c in report["checks"] if c["check"] == "loose_pattern")
    assert not loose["ok"]
    assert report["verdict"] == "BLOCKED"


def test_no_hardcoded_username_in_source() -> None:
    """DoD #4: el motor no lleva el username del autor hardcodeado."""
    src = Path(gate.__file__).read_text(encoding="utf-8")
    assert "fdl" not in src.lower().replace("default_pii_terms", "")


def test_loose_pattern_chunks_many_revs(tmp_path: Path, monkeypatch) -> None:
    """WinError 206 hotfix: cientos de revs no revientan la linea de comandos
    (se procesan en chunks) y el hallazgo del primer commit sigue cazandose.

    WOT-2026-020f: monkeypatch REV_CHUNK_SIZE a 5 para crear 15 commits (3
    chunks) en vez de 205. Testea la misma logica de chunking pero en <2s
    en vez de ~100s (gc.auto=0 + 205 loose objects = git progresivamente lento).
    """
    monkeypatch.setattr(gate, "REV_CHUNK_SIZE", 5)
    repo = _make_repo(tmp_path, "repo_grande")
    (repo / "leak.md").write_text("c--Users-pepito-x\n", encoding="utf-8")
    _git(repo, "add", "leak.md")
    _git(repo, "commit", "-m", "leak temprano")
    for i in range(gate.REV_CHUNK_SIZE * 2 + 5):
        (repo / "f.txt").write_text(f"v{i}\n", encoding="utf-8")
        _git(repo, "add", "f.txt")
        _git(repo, "commit", "-q", "-m", f"c{i}")
    report = gate.run_gate(repo, [], ["pepito"], [])
    loose = next(c for c in report["checks"] if c["check"] == "loose_pattern")
    assert not loose["ok"] and "leak.md" in str(loose["evidence"])


# --- WOT-2026-068w: gitleaks config in motor root ---


def _seed_bytes() -> bytes:
    """Return the seed content (canonical source)."""
    return gate.GITLEAKS_SEED.read_bytes()


def _setup_gitleaks_repo(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Create a test repo with .gitleaks.toml identical to seed, and point
    GITLEAKS_SEED to a temp copy so tests are hermetic."""
    fake_seed_dir = tmp_path / "seed"
    fake_seed_dir.mkdir()
    fake_seed = fake_seed_dir / "gitleaks.config.toml"
    fake_seed.write_bytes(_seed_bytes())
    monkeypatch.setattr(gate, "GITLEAKS_SEED", fake_seed)

    repo = _make_repo(tmp_path, "motor_fake")
    (repo / ".gitleaks.toml").write_bytes(_seed_bytes())
    return repo, fake_seed


def test_gitleaks_config_present_identical_passes(tmp_path: Path, monkeypatch) -> None:
    """D3: .gitleaks.toml present and identical to seed -> ok=True."""
    repo, _ = _setup_gitleaks_repo(tmp_path, monkeypatch)
    result = gate.check_gitleaks_config(repo)
    assert result["ok"] is True
    assert result["check"] == "gitleaks_config"
    assert result["evidence"]["cause"] is None
    assert result["evidence"]["config_hash"] is not None
    assert len(result["evidence"]["config_hash"]) == 12


def test_gitleaks_config_absent_fails(tmp_path: Path, monkeypatch) -> None:
    """D3: .gitleaks.toml absent -> ok=False, cause=ABSENT."""
    fake_seed_dir = tmp_path / "seed"
    fake_seed_dir.mkdir()
    fake_seed = fake_seed_dir / "gitleaks.config.toml"
    fake_seed.write_bytes(_seed_bytes())
    monkeypatch.setattr(gate, "GITLEAKS_SEED", fake_seed)

    repo = _make_repo(tmp_path, "motor_no_config")
    result = gate.check_gitleaks_config(repo)
    assert result["ok"] is False
    assert result["evidence"]["cause"] == "ABSENT"
    assert result["evidence"]["config_hash"] is None


def test_gitleaks_config_divergent_fails(tmp_path: Path, monkeypatch) -> None:
    """D3: .gitleaks.toml present but differs from seed -> ok=False, cause=DIVERGENT."""
    fake_seed_dir = tmp_path / "seed"
    fake_seed_dir.mkdir()
    fake_seed = fake_seed_dir / "gitleaks.config.toml"
    fake_seed.write_bytes(_seed_bytes())
    monkeypatch.setattr(gate, "GITLEAKS_SEED", fake_seed)

    repo = _make_repo(tmp_path, "motor_divergente")
    (repo / ".gitleaks.toml").write_text("title = 'divergent'\n", encoding="utf-8")
    result = gate.check_gitleaks_config(repo)
    assert result["ok"] is False
    assert result["evidence"]["cause"] == "DIVERGENT"
    assert result["evidence"]["config_hash"] is not None
    assert result["evidence"]["seed_hash"] is not None


def test_gitleaks_config_in_run_gate(tmp_path: Path, monkeypatch) -> None:
    """D3: check_gitleaks_config is wired into run_gate and affects verdict."""
    repo, _ = _setup_gitleaks_repo(tmp_path, monkeypatch)
    report = gate.run_gate(repo, [], ["x9z_nonexistent"], [])
    gitleaks = next(c for c in report["checks"] if c["check"] == "gitleaks_config")
    assert gitleaks["ok"] is True


def test_gitleaks_config_receipt_d4(tmp_path: Path, monkeypatch) -> None:
    """D4: publication receipt declares gitleaks config path + hash when ok."""
    repo, _ = _setup_gitleaks_repo(tmp_path, monkeypatch)
    report = gate.run_gate(repo, [], ["x9z_nonexistent"], [])
    assert report["gitleaks_config"] is not None
    assert "path" in report["gitleaks_config"]
    assert "hash" in report["gitleaks_config"]
    assert len(report["gitleaks_config"]["hash"]) == 12


def test_gitleaks_config_receipt_d4_absent(tmp_path: Path, monkeypatch) -> None:
    """D4: receipt is None when config check fails."""
    fake_seed_dir = tmp_path / "seed"
    fake_seed_dir.mkdir()
    fake_seed = fake_seed_dir / "gitleaks.config.toml"
    fake_seed.write_bytes(_seed_bytes())
    monkeypatch.setattr(gate, "GITLEAKS_SEED", fake_seed)

    repo = _make_repo(tmp_path, "motor_sin_config")
    report = gate.run_gate(repo, [], ["x9z_nonexistent"], [])
    assert report["gitleaks_config"] is None


def test_gitleaks_config_mutation_absent_and_divergent(
    tmp_path: Path, monkeypatch
) -> None:
    """D5: mutation with teeth -- rename (ABSENT) and delete rule (DIVERGENT)
    both make check_gitleaks_config fail; COPY-RESTORE brings it back."""
    repo, _ = _setup_gitleaks_repo(tmp_path, monkeypatch)
    config_path = repo / ".gitleaks.toml"
    backup_path = tmp_path / ".gitleaks.toml.bak"
    original_bytes = config_path.read_bytes()

    # m1: rename -> ABSENT
    config_path.rename(backup_path)
    result_absent = gate.check_gitleaks_config(repo)
    assert result_absent["ok"] is False
    assert result_absent["evidence"]["cause"] == "ABSENT"

    # Restore via COPY-RESTORE (never git checkout)
    shutil.copy2(backup_path, config_path)

    # m2: delete one rule -> DIVERGENT
    content = config_path.read_text(encoding="utf-8")
    content = content.replace(
        "'''sk-live-063c-SSEKEY-9f2c47ab''',\n",
        "",
    )
    config_path.write_text(content, encoding="utf-8")
    result_divergent = gate.check_gitleaks_config(repo)
    assert result_divergent["ok"] is False
    assert result_divergent["evidence"]["cause"] == "DIVERGENT"

    # Restore via COPY-RESTORE (never git checkout)
    shutil.copy2(backup_path, config_path)

    # After restore -> passes again
    result_restored = gate.check_gitleaks_config(repo)
    assert result_restored["ok"] is True

    # Full test file still passes
    assert config_path.read_bytes() == original_bytes
