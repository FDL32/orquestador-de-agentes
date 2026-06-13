from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts import classify_publication


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


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
