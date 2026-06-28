from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts import classify_publication


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


def test_blocks_fake_secret_in_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "settings.txt").write_text(
        "PUBLICATION_AUDIT_FAKE_SECRET=do-not-publish\n", encoding="utf-8"
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
    ignored_file.write_text(
        "PUBLICATION_AUDIT_FAKE_SECRET=ignored-by-git\n", encoding="utf-8"
    )

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
        "PUBLICATION_AUDIT_FAKE_SECRET=tracked\n", encoding="utf-8"
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
        "PUBLICATION_AUDIT_FAKE_SECRET=untracked\n", encoding="utf-8"
    )

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"
    assert manifest["tree_secret_scan"]["ok"] is False
    assert manifest["tree_secret_scan"]["findings"][0]["path"] == "new-secret.txt"


def test_blocks_realistic_secret_patterns(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "aws.txt").write_text(
        "aws_access_key_id = AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8"
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
    secret_file.write_text(
        "PUBLICATION_AUDIT_FAKE_SECRET=historical\n", encoding="utf-8"
    )
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
    content = "PUBLICATION_AUDIT_FAKE_SECRET=same-blob\n"
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
        "API_KEY=replace_with_your_actual_api_key_here\n", encoding="utf-8"
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
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8"
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
        "Local path: C:\\Users\\fdl\\private\\note.txt\n", encoding="utf-8"
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
_FIXTURE_SECRET = "sk-abcdefghijklmnopqrstuvwxyz0123456789\n"  # noqa: S105


def test_security_fixture_tree_scan_is_allowlisted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tests").mkdir()
    fixture = repo / "tests" / "test_redact.py"
    fixture.write_text(_FIXTURE_SECRET, encoding="utf-8")
    _git(repo, "add", "tests/test_redact.py")
    _git(repo, "commit", "-m", "add security fixture")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert manifest["tree_secret_scan"]["ok"] is True
    assert "tests/test_redact.py" not in flagged
    assert manifest["verdict"] != "BLOQUEADO_POR_SECRETO"


def test_non_allowlisted_fixture_path_still_blocks_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    prod = repo / "scripts" / "prod.py"
    prod.write_text(_FIXTURE_SECRET, encoding="utf-8")
    _git(repo, "add", "scripts/prod.py")
    _git(repo, "commit", "-m", "add prod secret")

    manifest = classify_publication.build_manifest(repo, scan_history=True)

    flagged = {f["path"] for f in manifest["tree_secret_scan"]["findings"]}
    assert manifest["tree_secret_scan"]["ok"] is False
    assert "scripts/prod.py" in flagged
    assert manifest["verdict"] == "BLOQUEADO_POR_SECRETO"


def test_security_fixture_history_scan_is_allowlisted(tmp_path: Path) -> None:
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

    # Contrast: same flow on a non-allowlisted path DOES surface in history.
    prod_repo = tmp_path / "prod_repo"
    _init_repo(prod_repo)
    (prod_repo / "scripts").mkdir()
    prod = prod_repo / "scripts" / "prod.py"
    prod.write_text(_FIXTURE_SECRET, encoding="utf-8")
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


def test_allowlist_is_per_named_path_not_an_evasion(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    evil = repo / "scripts" / "evil.py"
    evil.write_text("PUBLICATION_AUDIT_FAKE_SECRET=real\n", encoding="utf-8")
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
    leak.write_text('api_key = "sk_live_0123456789abcdefXYZ"\n', encoding="utf-8")
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
        "semicolon.js": "const token = REALSECRET0123456789abcdef;\n",
        "comma.py": "params = dict(token=REALSECRET0123456789abcdef, x=1)\n",
        "prose.txt": "password = SuperSecretValue123456 this is prod\n",
        "envfile.env": "TOKEN=valorsincomillas0123456789abcd\n",
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


def test_fixture_allowlist_is_case_sensitive_exact() -> None:
    """Platform-invariance guard: the security-fixture allowlist must match the
    exact posix path, never a case variant. On Windows ``fnmatch`` case-folds (via
    ``os.path.normcase``), so ``Tests/Test_Redact.py`` could impersonate
    ``tests/test_redact.py`` and publish a real fake-secret marker clean.

    This probes the predicate directly (not via on-disk files): a case-insensitive
    filesystem like Windows/NTFS collapses ``test_redact.py`` and
    ``Test_Redact.py`` into one inode, so the widening can only be exercised at the
    string level where the scanner actually compares repo-relative posix paths.
    """
    assert classify_publication._is_security_fixture_path("tests/test_redact.py")
    # Case variants must NOT be exempt -- they are scanned normally and block.
    assert not classify_publication._is_security_fixture_path("tests/Test_Redact.py")
    assert not classify_publication._is_security_fixture_path("TESTS/TEST_REDACT.PY")
    assert not classify_publication._is_security_fixture_path("tests/tEsT_rEdAcT.py")
    # Similar-but-different names must NOT be exempt either.
    assert not classify_publication._is_security_fixture_path(
        "tests/test_redact_extra.py"
    )
    assert not classify_publication._is_security_fixture_path(
        "src/tests/test_redact.py"
    )
