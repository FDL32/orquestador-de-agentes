from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts import classify_publication, encoding_guard


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _git_stdout(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")


# WOT-2026-016r: this module is itself a scanned surface. Its deliberate
# secret-like fixtures are ASSEMBLED at runtime so the module's own SOURCE does
# not embed a scannable literal; the scanner still sees the assembled value when
# it is written to a fixture file on disk, which is where the assertions run.
_FAKE_SENTINEL = "PUBLICATION_AUDIT_" + "FAKE_SECRET="
_OPAQUE_SECRET = "REALSECRET0123456789" + "abcdef"
_OPAQUE_PASSWORD = "SuperSecretValue" + "123456"
# Non-seed synthetic values: deliberately distinct from the seed's by-design
# fixtures so they remain genuine control positives (the seed values are now
# scrubbed by the classifier as BY DESIGN).
_LEAK_KEY = "sk_live_9f8e7d6c5b4a3210" + "XYZ"
_UNQUOTED_KEY = "valorsincomillas9f8e7d6c5b4a3210"
_ENV_PLACEHOLDER = "replace_with_your_" + "actual_api_key_here"
# A valid-format (non-example) AWS key id: AKIA + exactly 16 uppercase alnum.
# The documented example (AKIAIOSFODNN7EXAMPLE) is a BY-DESIGN placeholder, so
# it is never used to assert blocking -- this value is.
_REAL_AKIA = "AKIA" + "7Q2W9E4R6T8Y1U3I"
# A non-seed synthetic `sk-` value used as a genuine control positive.
_REAL_SK = "sk-" + "Zx9Y8w7V6u5T4s3R2q1P0o"


def test_blocks_fake_secret_in_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "settings.txt").write_text(
        _FAKE_SENTINEL + "do-not-publish\n", encoding="utf-8"
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert manifest["tree_secret_scan"]["ok"] is False
    assert manifest["tree_secret_scan"]["findings"][0]["path"] == "settings.txt"


def test_tree_scan_ignores_gitignored_secret(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".gitignore").write_text("legacy_docs/\n", encoding="utf-8")
    (repo / "legacy_docs").mkdir()
    ignored_file = repo / "legacy_docs" / "old.md"
    ignored_file.write_text(_FAKE_SENTINEL + "ignored-by-git\n", encoding="utf-8")

    check_ignore = _git_stdout(repo, "check-ignore", "-v", "legacy_docs/old.md")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged_paths = {
        finding["path"] for finding in manifest["tree_secret_scan"]["findings"]
    }
    assert ".gitignore:1:legacy_docs/" in check_ignore
    assert manifest["tree_secret_scan"]["ok"] is True
    assert "legacy_docs/old.md" not in flagged_paths
    assert manifest["verdict"] == "LISTO_PARA_PUBLICAR"


def test_tree_scan_detects_tracked_secret(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tracked-secret.txt").write_text(
        _FAKE_SENTINEL + "tracked\n", encoding="utf-8"
    )
    _git(repo, "add", "tracked-secret.txt")
    _git(repo, "commit", "-m", "add tracked secret")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert manifest["tree_secret_scan"]["ok"] is False
    assert manifest["tree_secret_scan"]["findings"][0]["path"] == "tracked-secret.txt"


def test_tree_scan_detects_untracked_non_ignored_secret(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "new-secret.txt").write_text(
        _FAKE_SENTINEL + "untracked\n", encoding="utf-8"
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert manifest["tree_secret_scan"]["ok"] is False
    assert manifest["tree_secret_scan"]["findings"][0]["path"] == "new-secret.txt"


def test_blocks_realistic_secret_patterns(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "aws.txt").write_text(
        f"aws_access_key_id = {_REAL_AKIA}\n", encoding="utf-8"
    )
    (repo / "key.pem").write_text(
        "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (repo / "jwt.txt").write_text(
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkZha2UifQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n",
        encoding="utf-8",
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    finding_paths = {
        finding["path"] for finding in manifest["tree_secret_scan"]["findings"]
    }
    excluded_paths = {
        item["path"] for item in manifest["publication_manifest"]["EXCLUDE_UNTRACKED"]
    }
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert {"aws.txt", "jwt.txt"}.issubset(finding_paths)
    assert "key.pem" in excluded_paths


def test_blocks_fake_secret_in_history_after_tree_cleanup(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    secret_file = repo / "old_secret.txt"
    secret_file.write_text(_FAKE_SENTINEL + "historical\n", encoding="utf-8")
    _git(repo, "add", "old_secret.txt")
    _git(repo, "commit", "-m", "add secret")
    secret_file.write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "old_secret.txt")
    _git(repo, "commit", "-m", "remove secret from tree")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert manifest["tree_secret_scan"]["ok"] is True
    assert manifest["history_secret_scan"]["ok"] is False
    assert manifest["history_secret_scan"]["findings"][0]["path"] == "old_secret.txt"
    assert "blob" in manifest["history_secret_scan"]["findings"][0]


def test_history_blob_reports_all_relevant_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    content = _FAKE_SENTINEL + "same-blob\n"
    (repo / "a.txt").write_text(content, encoding="utf-8")
    (repo / "b.txt").write_text(content, encoding="utf-8")
    _git(repo, "add", "a.txt", "b.txt")
    _git(repo, "commit", "-m", "add duplicated secret blob")
    (repo / "a.txt").write_text("clean a\n", encoding="utf-8")
    (repo / "b.txt").write_text("clean b\n", encoding="utf-8")
    _git(repo, "add", "a.txt", "b.txt")
    _git(repo, "commit", "-m", "clean tree")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    finding = manifest["history_secret_scan"]["findings"][0]
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert finding["paths"] == ["a.txt", "b.txt"]


def test_splits_exclude_tracked_from_exclude_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".env").write_text("SAFE_PLACEHOLDER=1\n", encoding="utf-8")
    _git(repo, "add", ".env")
    _git(repo, "commit", "-m", "track env accidentally")
    (repo / "orchestrator_pipeline").mkdir()
    (repo / "orchestrator_pipeline" / "report.md").write_text(
        "private report\n", encoding="utf-8"
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert ".env" in manifest["tracked_exclusions_need_human_action"]
    assert "orchestrator_pipeline/report.md" in manifest["gitignore_proposed"]
    assert manifest["verdict"] == "DECIDE_PENDING"
    assert any(
        reason["code"] == "EXCLUDE_TRACKED_PENDING"
        for reason in manifest["blocked_reasons"]
    )
    assert manifest["summary"]["EXCLUDE_TRACKED"] == 1
    assert manifest["summary"]["EXCLUDE_UNTRACKED"] == 1


def test_env_example_is_publishable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".env.example").write_text("API_KEY=\n", encoding="utf-8")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    publish_paths = {
        item["path"] for item in manifest["publication_manifest"]["PUBLISH"]
    }
    assert ".env.example" in publish_paths


def test_env_example_placeholder_does_not_block_publication(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".env.example").write_text(
        f"API_KEY={_ENV_PLACEHOLDER}\n", encoding="utf-8"
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    publish_paths = {
        item["path"] for item in manifest["publication_manifest"]["PUBLISH"]
    }
    assert manifest["tree_secret_scan"]["ok"] is True
    assert manifest["verdict"] == "LISTO_PARA_PUBLICAR"
    assert ".env.example" in publish_paths


def test_env_example_real_secret_still_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".env.example").write_text(
        f"AWS_ACCESS_KEY_ID={_REAL_AKIA}\n", encoding="utf-8"
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert manifest["tree_secret_scan"]["findings"][0]["path"] == ".env.example"


def test_binary_bytes_in_text_extension_go_to_decide(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "notes.md").write_bytes(b"title\x00hidden")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    decide_paths = {item["path"] for item in manifest["publication_manifest"]["DECIDE"]}
    assert "notes.md" in decide_paths
    assert manifest["verdict"] == "DECIDE_PENDING"


def test_decide_pending_prevents_ready_verdict(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "archive.bin").write_bytes(b"\x00\x01\x02")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "DECIDE_PENDING"
    assert manifest["summary"]["DECIDE"] == 1
    assert manifest["blocked_reasons"][0]["code"] == "DECIDE_PENDING"


def test_cli_returns_nonzero_for_decide_pending(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "archive.bin").write_bytes(b"\x00\x01\x02")

    rc = classify_publication.main(["--repo-root", str(repo)])

    assert rc == 3


def test_cli_returns_tool_error_code_for_non_git_repo(tmp_path: Path) -> None:
    repo = tmp_path / "missing-repo"

    rc = classify_publication.main(["--repo-root", str(repo)])

    assert rc == 2


def test_clean_repo_ready_to_publish_and_cli_zero(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    manifest = classify_publication.build_manifest(repo, scan_history=True)
    rc = classify_publication.main(["--repo-root", str(repo)])

    assert manifest["verdict"] == "LISTO_PARA_PUBLICAR"
    assert rc == 0


def test_cli_writes_json_with_out(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    out = tmp_path / "reports" / "publication_manifest.json"

    rc = classify_publication.main(["--repo-root", str(repo), "--out", str(out)])

    data = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0
    assert data["verdict"] == "LISTO_PARA_PUBLICAR"


def test_redaction_risk_has_redaction_verdict(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "notes.md").write_text(
        "Local path: C:\\Users\\testuser\\private\\note.txt\n", encoding="utf-8"
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "LISTO_CON_REDACTIONS"
    assert manifest["redactions_required"] is True
    assert manifest["summary"]["PUBLISH_WITH_REDACTIONS"] == 1


def test_quick_mode_never_returns_ready(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    manifest = classify_publication.build_manifest(repo, scan_history=False)
    rc = classify_publication.main(["--repo-root", str(repo), "--quick"])

    assert manifest["verdict"] == "NO_ACEPTAR_TODAVIA"
    assert manifest["history_secret_scan"]["enabled"] is False
    assert manifest["blocked_reasons"][0]["code"] == "HISTORY_SCAN_SKIPPED"
    assert rc == 3


def test_no_history_emits_deprecation_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    rc = classify_publication.main(["--repo-root", str(repo), "--no-history"])

    captured = capsys.readouterr()
    assert rc == 3
    assert "--no-history is deprecated" in captured.err


def test_dirty_during_scan_blocks_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    original_scan = classify_publication._scan_tree_secrets

    def mutate_then_scan(
        repo_root: Path,
        files: classify_publication.RepoFiles,
        text_cache: classify_publication.TextCache,
    ) -> list[dict[str, object]]:
        (repo_root / "late.md").write_text("late mutation\n", encoding="utf-8")
        return original_scan(repo_root, files, text_cache)

    monkeypatch.setattr(classify_publication, "_scan_tree_secrets", mutate_then_scan)

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "NO_ACEPTAR_TODAVIA"
    assert manifest["dirty_during_scan"] is True
    assert any(
        reason["code"] == "DIRTY_DURING_SCAN" for reason in manifest["blocked_reasons"]
    )


def test_head_change_during_scan_blocks_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    original_scan = classify_publication._scan_tree_secrets

    def commit_then_scan(
        repo_root: Path,
        files: classify_publication.RepoFiles,
        text_cache: classify_publication.TextCache,
    ) -> list[dict[str, object]]:
        (repo_root / "late.md").write_text("late mutation\n", encoding="utf-8")
        _git(repo_root, "add", "late.md")
        _git(repo_root, "commit", "-m", "late commit")
        return original_scan(repo_root, files, text_cache)

    monkeypatch.setattr(classify_publication, "_scan_tree_secrets", commit_then_scan)

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "NO_ACEPTAR_TODAVIA"
    assert manifest["head_changed_during_scan"] is True
    assert any(
        reason["code"] == "HEAD_CHANGED_DURING_SCAN"
        for reason in manifest["blocked_reasons"]
    )


def test_redaction_targets_are_limited(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "many.md").write_text(
        "\n".join(f"user{i}@example.com" for i in range(60)),
        encoding="utf-8",
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)
    redaction_file = manifest["publication_manifest"]["PUBLISH_WITH_REDACTIONS"][0]

    assert redaction_file["redaction_targets"]["truncated"] is True
    assert len(redaction_file["redaction_targets"]["targets"]) == 50


def test_motor_root_guard_blocks_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "MANIFEST.distribute").write_text("motor\n", encoding="utf-8")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["is_motor_root"] is True
    assert manifest["verdict"] == "NO_ACEPTAR_TODAVIA"
    assert any(
        reason["code"] == "MOTOR_ROOT_PUBLICATION_GUARD"
        for reason in manifest["blocked_reasons"]
    )


def test_motor_root_guard_can_be_explicitly_allowed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "MANIFEST.distribute").write_text("motor\n", encoding="utf-8")
    # Add a binary blob to force a DECIDE_PENDING verdict even after the guard
    # is bypassed (D3 moved .distribute to text; we need something that DECIDE).
    (repo / "data.bin").write_bytes(b"\x00\x01\x02")

    manifest = classify_publication.build_manifest(
        repo, scan_history=True, allow_motor_root=True
    )

    assert manifest["is_motor_root"] is True
    assert manifest["allow_motor_root"] is True
    assert manifest["verdict"] == "DECIDE_PENDING"
    assert all(
        reason["code"] != "MOTOR_ROOT_PUBLICATION_GUARD"
        for reason in manifest["blocked_reasons"]
    )


def test_out_path_is_excluded_from_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    out = repo / "custom-report.json"
    out.write_text("{}\n", encoding="utf-8")

    manifest = classify_publication.build_manifest(
        repo, scan_history=True, out_path=out
    )

    all_paths = {
        item["path"]
        for bucket in manifest["publication_manifest"].values()
        for item in bucket
    }
    assert "custom-report.json" not in all_paths


# Deliberate fake secret marker used as a scanner fixture, not a real credential.
# WOT-2026-016r: it is a BY-DESIGN VALUE (a known synthetic placeholder), exempt
# by EXACT VALUE, never by path.
_FIXTURE_SECRET = "sk-abcdefghijklmnopqrstuvwxyz0123456789\n"  # noqa: S105


def test_by_design_value_is_exempt_by_value_not_path(tmp_path: Path) -> None:
    """(iv) The exemption is by VALUE, not by PATH: a by-design placeholder is
    exempt wherever it appears, including a path that was never allowlisted."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "prod.py").write_text(_FIXTURE_SECRET, encoding="utf-8")
    _git(repo, "add", "scripts/prod.py")
    _git(repo, "commit", "-m", "add by-design placeholder to a prod path")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert manifest["tree_secret_scan"]["ok"] is True
    assert "scripts/prod.py" not in flagged


def test_real_secret_in_prod_path_still_blocks_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    prod = repo / "scripts" / "prod.py"
    prod.write_text(f"AWS_KEY = '{_REAL_AKIA}'\n", encoding="utf-8")
    _git(repo, "add", "scripts/prod.py")
    _git(repo, "commit", "-m", "add prod secret")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert manifest["tree_secret_scan"]["ok"] is False
    assert "scripts/prod.py" in flagged
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_ap_d04_real_secret_in_formerly_allowlisted_path_still_blocks(
    tmp_path: Path,
) -> None:
    """AP-D04 control positive (v). The old exemption was PATH-based
    (`SECURITY_FIXTURE_PATHS` -> zero patterns), so a REAL secret in
    `tests/test_redact.py` was never scanned. It is now VALUE-based: the
    by-design placeholder in that same file is excised, but a real secret beside
    it still blocks.

    Literal command: `python scripts/classify_publication.py --repo-root <fixture>`
    must exit 1 (BLOQUEADO_POR_SECRETO).
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_redact.py").write_text(
        _FIXTURE_SECRET + f"AWS_KEY = '{_REAL_AKIA}'\n", encoding="utf-8"
    )
    _git(repo, "add", "tests/test_redact.py")
    _git(repo, "commit", "-m", "one allowlisted path: placeholder + real secret")

    manifest = classify_publication.build_manifest(repo, scan_history=True)
    rc = classify_publication.main(["--repo-root", str(repo)])

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert "tests/test_redact.py" in flagged
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert rc == 1


def test_security_fixture_history_scan_is_allowlisted_by_value(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tests").mkdir()
    fixture = repo / "tests" / "test_redact.py"
    fixture.write_text(_FIXTURE_SECRET, encoding="utf-8")
    _git(repo, "add", "tests/test_redact.py")
    _git(repo, "commit", "-m", "add fixture secret")
    fixture.write_text("# clean fixture\n", encoding="utf-8")
    _git(repo, "add", "tests/test_redact.py")
    _git(repo, "commit", "-m", "clean fixture tree")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    history_paths = {
        path
        for finding in manifest["history_secret_scan"]["findings"]
        for path in finding["paths"]
    }
    assert "tests/test_redact.py" not in history_paths
    assert manifest["verdict"] != "BLOQUEADO_POR_SECRETO"

    # Contrast: a REAL secret through the same flow DOES surface in history.
    prod_repo = tmp_path / "prod_repo"
    _init_repo(prod_repo)
    (prod_repo / "scripts").mkdir()
    prod = prod_repo / "scripts" / "prod.py"
    prod.write_text(f"AWS_KEY = '{_REAL_AKIA}'\n", encoding="utf-8")
    _git(prod_repo, "add", "scripts/prod.py")
    _git(prod_repo, "commit", "-m", "add prod secret")
    prod.write_text("# clean\n", encoding="utf-8")
    _git(prod_repo, "add", "scripts/prod.py")
    _git(prod_repo, "commit", "-m", "clean prod tree")

    prod_manifest = classify_publication.build_manifest(prod_repo, scan_history=True)
    prod_history_paths = {
        path
        for finding in prod_manifest["history_secret_scan"]["findings"]
        for path in finding["paths"]
    }
    assert prod_manifest["tree_secret_scan"]["ok"] is True
    assert prod_manifest["history_secret_scan"]["ok"] is False
    assert "scripts/prod.py" in prod_history_paths
    assert prod_manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_mutation_placeholder_green_real_secret_red(tmp_path: Path) -> None:
    """MUTATION with both rc published over the SAME fixture shape.

    GREEN: the fixture carries only the by-design placeholder -> rc 0.
    RED:   the same fixture gains a real secret -> rc 1.
    The two rc are the observable system error proving the migration did not open
    a blind spot (containment verified by the SYSTEM, not by the model).
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tests").mkdir()
    fixture = repo / "tests" / "test_redact.py"

    fixture.write_text(_FIXTURE_SECRET, encoding="utf-8")
    _git(repo, "add", "tests/test_redact.py")
    _git(repo, "commit", "-m", "by-design placeholder only")
    rc_green = classify_publication.main(["--repo-root", str(repo)])

    fixture.write_text(
        _FIXTURE_SECRET + f"AWS_KEY = '{_REAL_AKIA}'\n", encoding="utf-8"
    )
    _git(repo, "add", "tests/test_redact.py")
    _git(repo, "commit", "-m", "add a real secret")
    rc_red = classify_publication.main(["--repo-root", str(repo)])

    assert rc_green == 0
    assert rc_red == 1


def test_allowlist_is_per_named_path_not_an_evasion(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    evil = repo / "scripts" / "evil.py"
    evil.write_text(_FAKE_SENTINEL + "real\n", encoding="utf-8")
    _git(repo, "add", "scripts/evil.py")
    _git(repo, "commit", "-m", "add evil secret")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    tree_flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert manifest["tree_secret_scan"]["ok"] is False
    assert "scripts/evil.py" in tree_flagged

    evil.write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "scripts/evil.py")
    _git(repo, "commit", "-m", "clean evil tree")

    manifest_after = classify_publication.build_manifest(repo, scan_history=True)
    history_paths = {
        path
        for finding in manifest_after["history_secret_scan"]["findings"]
        for path in finding["paths"]
    }
    assert manifest_after["history_secret_scan"]["ok"] is False
    assert "scripts/evil.py" in history_paths
    assert manifest_after["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_generic_pattern_ignores_code_but_blocks_literal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    parser = repo / "scripts" / "parser.py"
    parser.write_text('token = normalized.rstrip(",").strip()\n', encoding="utf-8")
    leak = repo / "scripts" / "leak.py"
    leak.write_text(f'api_key = "{_LEAK_KEY}"\n', encoding="utf-8")
    _git(repo, "add", "scripts/parser.py", "scripts/leak.py")
    _git(repo, "commit", "-m", "add parser and leak")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert "scripts/parser.py" not in flagged
    assert "scripts/leak.py" in flagged
    assert manifest["tree_secret_scan"]["ok"] is False
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_generic_pattern_blocks_opaque_secret_with_trailing_punctuation(
    tmp_path: Path,
) -> None:
    """Fail-closed regression guard: an opaque credential value terminated by a
    statement separator (``;`` ``,`` ``)``) or trailing prose must still block.
    A prior refinement anchored the unquoted branch at end-of-line and let these
    leak. Each case is an opaque blob (no ``.``/``(`` in the value), not code.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    leaks = {
        "semicolon.js": f"const token = {_OPAQUE_SECRET};\n",
        "comma.py": f"params = dict(token={_OPAQUE_SECRET}, x=1)\n",
        "prose.txt": f"password = {_OPAQUE_PASSWORD} this is prod\n",
        "envfile.env": f"TOKEN={_UNQUOTED_KEY}\n",
    }
    for name, content in leaks.items():
        (repo / "scripts" / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "scripts")
    _git(repo, "commit", "-m", "add opaque-secret leak cases")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    for name in leaks:
        assert f"scripts/{name}" in flagged, f"{name} must block (opaque secret)"
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_seed_values_are_derived_not_duplicated() -> None:
    """(iv) The BY-DESIGN value set is DERIVED from the seed's
    ``[[allowlists]].regexes`` -- not a hardcoded copy -- so the gate's exemption
    can never silently drift from the seed it claims to honour (the failure mode
    of WOT-2026-039k)."""
    seed_values = classify_publication._seed_allowlist_values()
    assert seed_values, "the motor ships the gitleaks seed next to the script"
    assert seed_values <= classify_publication.BY_DESIGN_VALUES


def test_by_design_exemption_is_case_sensitive_exact() -> None:
    """Value-exactness guard: the by-design exemption matches the EXACT literal,
    never a case variant or a near lookalike. A case-folded placeholder -- or any
    different value -- is scanned normally and still blocks, so the exemption can
    never widen into a way to publish a lookalike secret."""
    value = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
    assert value in classify_publication.BY_DESIGN_VALUES
    # The exact value is excised...
    assert classify_publication._scrub_by_design_values(value) == ""
    # ...but a case variant is NOT (the scrub is exact, not case-folded), and
    # neither is a lookalike with one character changed.
    upper = value.upper()
    lookalike = value.replace("w", "v")
    assert classify_publication._scrub_by_design_values(upper) == upper
    assert classify_publication._scrub_by_design_values(lookalike) == lookalike


# ---------------------------------------------------------------------------
# WOT-2026-015e: accepted-exception policy (D1-D6). Each block pairs a positive
# (the exception is recognized) with a negative (the exception never widens into
# a way to publish a real secret or a non-exempt path).
# ---------------------------------------------------------------------------


def test_d1_tests_redaction_fixture_is_not_a_redaction(tmp_path: Path) -> None:
    """D1: a benign redaction pattern (email, local path) under tests/ is a
    fixture by design -- it must NOT push the file into PUBLISH_WITH_REDACTIONS
    and must NOT block a clean repo from reaching LISTO_PARA_PUBLICAR."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_fixture.py").write_text(
        "SAMPLE_EMAIL = 'test@example.com'\n"
        "SAMPLE_PATH = r'C:\\Users\\testuser\\private\\note.txt'\n",
        encoding="utf-8",
    )
    _git(repo, "add", "tests/test_fixture.py")
    _git(repo, "commit", "-m", "add redaction fixture")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    redaction_paths = {
        item["path"]
        for item in manifest["publication_manifest"]["PUBLISH_WITH_REDACTIONS"]
    }
    assert "tests/test_fixture.py" not in redaction_paths
    assert manifest["verdict"] == "LISTO_PARA_PUBLICAR"


def test_d1_real_secret_under_tests_still_blocks(tmp_path: Path) -> None:
    """D1 security barrier: the tests/ allowlist suppresses ONLY redaction_risk.
    A real secret pattern (AKIA, sk-) under tests/ -- on any path, including the
    ones that used to be path-exempt security fixtures -- must still hard-block
    the tree scan. If this ever passes, the allowlist has become a secret-evasion
    (WOT-2026-016r moved the exemption from PATH to EXACT VALUE)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_leak.py").write_text(
        f"AWS_KEY = '{_REAL_AKIA}'\n", encoding="utf-8"
    )
    (repo / "tests" / "test_sk_leak.py").write_text(
        f"OPENAI = '{_REAL_SK}'\n",
        encoding="utf-8",
    )
    _git(repo, "add", "tests/test_leak.py", "tests/test_sk_leak.py")
    _git(repo, "commit", "-m", "add real secrets under tests")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert manifest["tree_secret_scan"]["ok"] is False
    assert "tests/test_leak.py" in flagged
    assert "tests/test_sk_leak.py" in flagged
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_d1_redaction_outside_tests_is_unaffected(tmp_path: Path) -> None:
    """D1 scope guard: the allowlist applies ONLY to tests/. A real dev path in
    a production file (src/, scripts/) must still require redaction."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "tool.py").write_text(
        "# see C:\\Users\\testuser\\private\\note.txt\n", encoding="utf-8"
    )
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-m", "add prod file with dev path")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    redaction_paths = {
        item["path"]
        for item in manifest["publication_manifest"]["PUBLISH_WITH_REDACTIONS"]
    }
    assert "scripts/tool.py" in redaction_paths
    assert manifest["redactions_required"] is True


@pytest.mark.parametrize(
    ("sample", "should_match"),
    [
        (".env.local", False),
        ("settings.local.json", False),
        ("foo.local.json", False),
        ("host .env.local config", False),
        ("env.localhost", False),
        ("api.internal.local", True),
        ("db.prod.local", True),
        ("myhost.local", True),
        ("printer.local", True),
        ("connect to mybox.local now", True),
    ],
)
def test_d2_local_regex_distinguishes_hostname_from_filename(
    sample: str, should_match: bool
) -> None:
    """D2: the refined .local pattern must treat dotfile/filename forms
    (.env.local, settings.local.json) as NON-matches while still catching real
    mDNS/AD hostnames -- including the single-segment myhost.local that the
    previous two-segment-required regex let leak."""
    local_pattern = classify_publication.REDACTION_PATTERNS[-1]
    assert bool(local_pattern.search(sample)) is should_match


def test_d2_hostname_in_doc_triggers_redaction(tmp_path: Path) -> None:
    """D2 end-to-end: a real .local hostname in a normal doc still routes to
    PUBLISH_WITH_REDACTIONS (the regex refinement narrows false positives, it
    does not disable hostname redaction)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "ops.md").write_text("Deploy target: db.prod.local\n", encoding="utf-8")
    _git(repo, "add", "ops.md")
    _git(repo, "commit", "-m", "add ops doc")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    redaction_paths = {
        item["path"]
        for item in manifest["publication_manifest"]["PUBLISH_WITH_REDACTIONS"]
    }
    assert "ops.md" in redaction_paths


@pytest.mark.parametrize(
    "name",
    ["MANIFEST.distribute", "MANIFEST.workspace", "data.jsonl", "uv.lock"],
)
def test_d3_new_text_extensions_avoid_decide(tmp_path: Path, name: str) -> None:
    """D3: .distribute/.workspace/.jsonl/.lock are text. A clean file with one
    of these suffixes must classify as PUBLISH, not fall through to DECIDE as an
    unknown binary-ish type."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / name).write_text("plain text content\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", "add " + name)

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    publish_paths = {
        item["path"] for item in manifest["publication_manifest"]["PUBLISH"]
    }
    decide_paths = {item["path"] for item in manifest["publication_manifest"]["DECIDE"]}
    assert name in publish_paths
    assert name not in decide_paths


@pytest.mark.parametrize(
    "name", ["MI_PROYECTO.bat", "validate_template.bat", "VERIFY_VERSION.sh"]
)
def test_d4_gitignored_qa_scripts_do_not_surface(tmp_path: Path, name: str) -> None:
    """D4 (revised): the three local QA launchers are handled by untracking +
    .gitignore, NOT by EXCLUDE_PATTERNS. A gitignored, untracked launcher on disk
    must not appear in any bucket (git --exclude-standard filters it) and must
    not block the verdict. Keeping them out of EXCLUDE_PATTERNS is deliberate:
    EXCLUDE files are skipped by the secret scanner, and a .bat/.sh is publishable
    code that must not live in the scanner's blind spot (see the guard below)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".gitignore").write_text("/" + name + "\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore local qa launcher")
    (repo / name).write_text("echo local qa\n", encoding="utf-8")  # untracked + ignored

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    all_paths = {
        item["path"]
        for bucket in manifest["publication_manifest"].values()
        for item in bucket
    }
    assert name not in all_paths
    assert manifest["verdict"] == "LISTO_PARA_PUBLICAR"


@pytest.mark.parametrize(
    "name", ["MI_PROYECTO.bat", "validate_template.bat", "VERIFY_VERSION.sh"]
)
def test_d4_qa_name_is_not_a_secret_scan_blind_spot(tmp_path: Path, name: str) -> None:
    """D4 security barrier (regression guard): the QA launcher names must NOT be
    in EXCLUDE_PATTERNS, because EXCLUDE files are skipped by the tree/history
    secret scanners. If they were excluded, a real secret committed under one of
    these names (especially surviving only in git history) would pass the gate.
    A tracked launcher carrying a real AKIA must still hard-block."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / name).write_text(f"set KEY={_REAL_AKIA}\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", "add launcher with real secret")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert name in flagged
    assert manifest["tree_secret_scan"]["ok"] is False
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_d4_unrelated_bat_sh_is_evaluated_normally(tmp_path: Path) -> None:
    """D4 scope guard: a different shell script is evaluated normally (no broad
    *.bat/*.sh exclusion); it must NOT be silently dropped into EXCLUDE_TRACKED."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "install.sh").write_text("#!/bin/sh\necho install\n", encoding="utf-8")
    _git(repo, "add", "install.sh")
    _git(repo, "commit", "-m", "add real installer")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    excluded = {
        item["path"] for item in manifest["publication_manifest"]["EXCLUDE_TRACKED"]
    }
    assert "install.sh" not in excluded


# ---------------------------------------------------------------------------
# WOT-2026-068b: an ASCII .bat must not condemn a destination to DECIDE_PENDING
# ---------------------------------------------------------------------------


def test_b68b_ascii_bat_classifies_publish(tmp_path: Path) -> None:
    """B4: a clean ASCII .bat launcher classifies as PUBLISH. Before this ticket
    the suffix-based branch routed it to DECIDE with the reason
    binary_large_or_unknown_type, which was false in both terms (ASCII, 571 B),
    and the whole repo verdict jammed at DECIDE_PENDING."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "run_checks.bat").write_text(
        "@echo off\r\nrem ASCII build launcher\r\necho ok\r\n", encoding="utf-8"
    )
    _git(repo, "add", "run_checks.bat")
    _git(repo, "commit", "-m", "add ascii bat launcher")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    publish_paths = {
        item["path"] for item in manifest["publication_manifest"]["PUBLISH"]
    }
    decide_items = {
        item["path"]: item for item in manifest["publication_manifest"]["DECIDE"]
    }
    assert "run_checks.bat" in publish_paths
    assert "run_checks.bat" not in decide_items
    assert "binary_large_or_unknown_type" not in (
        decide_items.get("run_checks.bat", {}).get("reasons", [])
    )


def test_b68b_binary_bat_still_decides_by_content(tmp_path: Path) -> None:
    """Content fail-closed survives the extension addition: a .bat whose bytes
    are actually binary (NUL in the first 4096) must still route to DECIDE, now
    via binary_in_text_file, not silently PUBLISH."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "corrupt.bat").write_bytes(b"@echo off\x00\x01\x02not ascii at all")
    _git(repo, "add", "corrupt.bat")
    _git(repo, "commit", "-m", "add binary bat")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    decide_items = {
        item["path"]: item for item in manifest["publication_manifest"]["DECIDE"]
    }
    assert "corrupt.bat" in decide_items
    assert "binary_in_text_file" in decide_items["corrupt.bat"]["reasons"]


def test_b68b_unknown_binary_extension_still_decides(tmp_path: Path) -> None:
    """Mutation control for the extension route: adding .bat must not soften the
    unknown-extension branch. A real binary with a never-listed suffix still
    classifies DECIDE with binary_large_or_unknown_type."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "payload.weirdext").write_bytes(b"\x7fELF\x00\x01\x02\x00binary blob")
    _git(repo, "add", "payload.weirdext")
    _git(repo, "commit", "-m", "add unknown binary")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    decide_items = {
        item["path"]: item for item in manifest["publication_manifest"]["DECIDE"]
    }
    assert "payload.weirdext" in decide_items
    assert "binary_large_or_unknown_type" in decide_items["payload.weirdext"]["reasons"]


def test_b68b_bat_is_text_in_both_guards_and_sh_keeps_audit() -> None:
    """Cross-file alignment (contract Integracion): .bat must be a text
    extension in classify_publication AND in encoding_guard, otherwise the
    extension route publishes .bat files that no encoding audit ever reads.
    Forbidden-surface guard: .sh keeps its place in encoding_guard's list, so
    no file is left at zero encoding audit by this change."""
    assert ".bat" in classify_publication.TEXT_EXTENSIONS
    assert ".bat" in encoding_guard.TEXT_EXTENSIONS
    assert ".sh" in encoding_guard.TEXT_EXTENSIONS


def test_d5_runtime_keep_tracked_not_flagged_for_human_action(tmp_path: Path) -> None:
    """D5: the three WOT-2026-015c KEEP files remain EXCLUDE_TRACKED but are
    accepted-by-design, so they must NOT appear in
    tracked_exclusions_need_human_action (which would block the verdict)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    keep = [
        ".agent/runtime/__init__.py",
        ".agent/runtime/memory/memory_helpers.py",
        ".agent/runtime/memory/memory_architecture.md",
    ]
    for rel in keep:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# kept by design\n", encoding="utf-8")
    _git(repo, "add", *keep)
    _git(repo, "commit", "-m", "track runtime keep files")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    need_action = set(manifest["tracked_exclusions_need_human_action"])
    for rel in keep:
        assert rel not in need_action


def test_d5_other_tracked_exclusion_still_needs_human_action(tmp_path: Path) -> None:
    """D5 scope guard: the allowlist covers only the three named KEEP files. Any
    other tracked-but-excluded file must still demand human action."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".env").write_text("SAFE_PLACEHOLDER=1\n", encoding="utf-8")
    _git(repo, "add", ".env")
    _git(repo, "commit", "-m", "track env accidentally")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert ".env" in manifest["tracked_exclusions_need_human_action"]


def test_d6a_accepted_history_path_does_not_block(tmp_path: Path) -> None:
    """D6a: a history blob whose only path is an accepted placeholder
    (skills/adopt-existing-project/SKILL.md) is accepted by design and must not
    surface as a history finding."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    accepted = repo / "skills" / "adopt-existing-project" / "SKILL.md"
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text(_FAKE_SENTINEL + "placeholder\n", encoding="utf-8")
    _git(repo, "add", "skills/adopt-existing-project/SKILL.md")
    _git(repo, "commit", "-m", "add accepted placeholder")
    accepted.write_text("# clean skill\n", encoding="utf-8")
    _git(repo, "add", "skills/adopt-existing-project/SKILL.md")
    _git(repo, "commit", "-m", "clean accepted tree")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    history_paths = {
        path
        for finding in manifest["history_secret_scan"]["findings"]
        for path in finding["paths"]
    }
    assert "skills/adopt-existing-project/SKILL.md" not in history_paths
    assert manifest["history_secret_scan"]["ok"] is True


def test_d6a_non_accepted_history_path_still_blocks(tmp_path: Path) -> None:
    """D6a scope guard: the same fake-secret in a non-accepted path still blocks
    via the history scan -- the accepted-path set is not a global bypass."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    other = repo / "skills" / "other-skill" / "SKILL.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(_FAKE_SENTINEL + "placeholder\n", encoding="utf-8")
    _git(repo, "add", "skills/other-skill/SKILL.md")
    _git(repo, "commit", "-m", "add non-accepted placeholder")
    other.write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "skills/other-skill/SKILL.md")
    _git(repo, "commit", "-m", "clean tree")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    history_paths = {
        path
        for finding in manifest["history_secret_scan"]["findings"]
        for path in finding["paths"]
    }
    assert "skills/other-skill/SKILL.md" in history_paths
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_d6b_meta_doc_path_suppresses_redaction(tmp_path: Path) -> None:
    """D6b: the motor own meta-docs (CHANGELOG.md, etc.) intentionally cite
    example dev paths. redaction_risk is suppressed for those exact paths."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "CHANGELOG.md").write_text(
        "Documented example path: C:\\Users\\testuser\\example\\file.md\n",
        encoding="utf-8",
    )
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-m", "add changelog with example path")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    redaction_paths = {
        item["path"]
        for item in manifest["publication_manifest"]["PUBLISH_WITH_REDACTIONS"]
    }
    assert "CHANGELOG.md" not in redaction_paths


def test_d6b_meta_doc_allowlist_does_not_suppress_secrets(tmp_path: Path) -> None:
    """D6b security barrier: META_DOC_PATHS suppresses only redaction_risk. A
    real secret in one of those exact docs must still hard-block the tree."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "CHANGELOG.md").write_text(f"Leaked: {_REAL_AKIA}\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-m", "add changelog with real secret")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert "CHANGELOG.md" in flagged
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_d6b_non_meta_doc_still_redacts_dev_path(tmp_path: Path) -> None:
    """D6b scope guard: a normal doc (not in META_DOC_PATHS) with a dev path
    must still require redaction -- the meta-doc set is exact, not a glob."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "GUIDE.md").write_text(
        "Edit C:\\Users\\testuser\\private\\note.txt\n", encoding="utf-8"
    )
    _git(repo, "add", "GUIDE.md")
    _git(repo, "commit", "-m", "add guide with dev path")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    redaction_paths = {
        item["path"]
        for item in manifest["publication_manifest"]["PUBLISH_WITH_REDACTIONS"]
    }
    assert "GUIDE.md" in redaction_paths


def test_d6b_scanner_self_match_is_suppressed() -> None:
    """D6b self-reference: classify_publication.py is in META_DOC_PATHS because
    its own source literally contains the REDACTION_PATTERNS (e.g. the
    ``/home/...`` regex matches its own definition). Suppressing redaction_risk
    for the scanner avoids a spurious self-flag. The secret branch is unaffected:
    this only covers redaction_risk, never secret_risk."""
    src = Path(classify_publication.__file__).read_text(encoding="utf-8")
    # The source genuinely contains at least one redaction-pattern self-match...
    assert any(pat.search(src) for pat in classify_publication.REDACTION_PATTERNS)
    # ...yet _content_flags suppresses redaction_risk for the scanner's own path.
    flags = classify_publication._content_flags(src, "scripts/classify_publication.py")
    assert "redaction_risk" not in flags
    # Scope guard: the same source under any OTHER path is NOT exempt.
    other_flags = classify_publication._content_flags(src, "scripts/other.py")
    assert "redaction_risk" in other_flags


# A real RSA/PKCS8 key body: 4 lines of base64-looking filler, well past the
# 64-char minimum the refined CRITICAL pattern requires. Assembled at runtime
# so this module's own source is not itself a scannable PEM block.
_REAL_PEM_BODY = "\n".join(
    "MIIEowIBAAKCAQEA" + ("Zm9vYmFyMTIzNDU2Nzg5" * 3) for _ in range(4)
)
_REAL_RSA_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    + _REAL_PEM_BODY
    + "\n-----END RSA PRIVATE KEY-----\n"
)
_REAL_PKCS8_KEY = (
    "-----BEGIN PRIVATE KEY-----\n" + _REAL_PEM_BODY + "\n-----END PRIVATE KEY-----\n"
)
# A bare header with no body (or a short synthetic stub): the shape of every
# historical fixture in this motor's own git log, which must stay by-design.
_BARE_PEM_HEADER = "-----BEGIN RSA PRIVATE KEY-----\n"


def test_regression_real_pem_key_body_still_blocks_tree(tmp_path: Path) -> None:
    """Regression (caught by Revisor-nan, WOT-2026-016r): KNOWN_EXAMPLE_PLACEHOLDERS
    used to list the bare PEM header as a by-design marker, and its value-exact
    scrub erased the ONLY pattern that detected a real key pasted into text --
    a real RSA/PKCS8 key passed clean (rc 0) after the migration. The fix
    requires a substantial base64 body after the header; this asserts both key
    types still block in the TREE scan."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "docs").mkdir()

    for name, key_text in (
        ("notes_rsa.md", _REAL_RSA_KEY),
        ("notes_pkcs8.md", _REAL_PKCS8_KEY),
    ):
        (repo / "docs" / name).write_text(key_text, encoding="utf-8")
        _git(repo, "add", f"docs/{name}")
        _git(repo, "commit", "-m", f"add {name}")

        rc = classify_publication.main(["--repo-root", str(repo)])
        assert rc == 1, f"{name}: a real key body must still block (rc=1)"

        manifest = classify_publication.build_manifest(repo, scan_history=False)
        assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_bare_pem_header_without_body_stays_by_design(tmp_path: Path) -> None:
    """The flip side of the regression test: a BARE header with no real key
    body (the shape of every historical fixture in this motor's own git log,
    e.g. a 3-char or 14-char stub) must NOT block -- only a substantial body
    makes it a real key, never the header alone."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tests").mkdir()
    fixture = repo / "tests" / "test_redact.py"
    fixture.write_text(_BARE_PEM_HEADER + "abc\n", encoding="utf-8")
    _git(repo, "add", "tests/test_redact.py")
    _git(repo, "commit", "-m", "bare header stub, no real key body")

    rc = classify_publication.main(["--repo-root", str(repo)])
    assert rc == 0, "a bare PEM header stub must not be flagged as a real key"
