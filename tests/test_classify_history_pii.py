from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import classify_publication as cp


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _commit_file(repo: Path, rel: str, content: str, msg: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", msg)


def _classify(repo: Path) -> dict:
    return cp.build_manifest(repo, scan_history=True)


def test_real_email_in_deleted_blob_blocks(tmp_path: Path) -> None:
    """DoD #1 (H1): PII en blob antiguo, ya BORRADO del tree, es detectada."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(
        repo,
        "notas.md",
        "contacto: persona.real@dominioprivado.es\n",
        "add notas con email",
    )
    _git(repo, "rm", "notas.md")
    _git(repo, "commit", "-m", "remove notas (pero el blob sigue en historia)")
    _commit_file(repo, "README.md", "# limpio\n", "tree limpio")

    manifest = _classify(repo)

    assert manifest["history_pii_scan"]["ok"] is False
    codes = {r["code"] for r in manifest["blocked_reasons"]}
    assert "HISTORY_PII_PENDING" in codes
    assert manifest["verdict"] != "LISTO_PARA_PUBLICAR"
    # la muestra esta ENMASCARADA: nunca se reproduce la PII entera
    samples = manifest["history_pii_scan"]["findings"][0]["samples"]
    assert all("persona.real@dominioprivado.es" not in s for s in samples)
    assert any("***" in s for s in samples)


def test_local_user_path_in_history_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(
        repo,
        "config_old.md",
        "ruta: C:\\Users\\pepe\\Dropbox\\datos\n",
        "add config con ruta",
    )
    _git(repo, "rm", "config_old.md")
    _git(repo, "commit", "-m", "remove config")

    manifest = _classify(repo)

    assert manifest["history_pii_scan"]["ok"] is False
    assert {r["code"] for r in manifest["blocked_reasons"]} >= {"HISTORY_PII_PENDING"}


def test_placeholders_do_not_block(tmp_path: Path) -> None:
    """DoD #2: redacciones legitimas y ejemplos NO bloquean el gate."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(
        repo,
        "docs.md",
        (
            "ruta redactada: C:\\Users\\<user>\\proyecto\n"
            "email ejemplo: cliente@example.com\n"
            "email redactado: <redacted-email>\n"
            "meta: 123+bot@users.noreply.github.com\n"
            "home doc: /home/user\n"
        ),
        "docs con placeholders",
    )

    manifest = _classify(repo)

    assert manifest["history_pii_scan"]["ok"] is True
    assert "HISTORY_PII_PENDING" not in {r["code"] for r in manifest["blocked_reasons"]}


def test_mutation_without_patterns_false_green_returns(
    tmp_path: Path, monkeypatch
) -> None:
    """DoD #3 (MUTATION): sin REDACTION_PATTERNS el hallazgo desaparece ->
    demuestra que el scan es la barrera, no cosmetico."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "leak.md", "mail: persona.real@dominioprivado.es\n", "leak")
    _git(repo, "rm", "leak.md")
    _git(repo, "commit", "-m", "rm")

    monkeypatch.setattr(cp, "REDACTION_PATTERNS", [])
    manifest = _classify(repo)

    assert manifest["history_pii_scan"]["ok"] is True  # falso verde reproducido
