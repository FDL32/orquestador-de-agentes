"""Tests for the integrated motor<->destino gate — WOT-2026-008f.

The wrapper delegates to live checks; these tests build isolated motor/destino
layouts in tmp_path (never mutating a real repo_destino) and verify the wrapper
fails closed on a broken link / authority, propagates the pre-push gate exit
code, and runs the first-publication audit only behind the explicit flag.

[NON-REVERSE-CLASSICAL: new integration gate, not a bug fix]
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.check_motor_destination_integration as wrapper
from scripts.check_motor_destination_integration import (
    EXIT_CHECK_FAILED,
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_STATUS_NOT_PUBLISHABLE,
    check_destination_authority,
    check_link,
    main,
    run_integration,
    run_publication_audit,
)


def _seed_destino(
    tmp_path: Path,
    *,
    motor_root: Path,
    with_link: bool = True,
    with_workplan: bool = True,
    destination_root_override: str | None = None,
) -> Path:
    """Build an isolated repo_destino with .agent/collaboration + link."""
    destino = tmp_path / "destino"
    collab = destino / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    if with_workplan:
        (collab / "work_plan.md").write_text(
            "# work_plan.md -- WOT-2026-008f\n", encoding="utf-8"
        )
    if with_link:
        cfg = destino / ".agent" / "config"
        cfg.mkdir(parents=True)
        link = {
            "motor_root": str(motor_root),
            "destination_root": destination_root_override or str(destino),
        }
        (cfg / "motor_destination_link.json").write_text(
            json.dumps(link), encoding="utf-8"
        )
    return destino


class TestCheckLink:
    def test_missing_link_fails_closed(self, tmp_path):
        destino = _seed_destino(tmp_path, motor_root=tmp_path, with_link=False)
        ok, diag = check_link(destino, None)
        assert ok is False
        assert "missing or invalid" in diag

    def test_invalid_json_fails_closed(self, tmp_path):
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        link = destino / ".agent" / "config" / "motor_destination_link.json"
        link.write_text("{ not json", encoding="utf-8")
        ok, _diag = check_link(destino, None)
        assert ok is False

    def test_destination_root_mismatch_fails(self, tmp_path):
        destino = _seed_destino(
            tmp_path, motor_root=tmp_path, destination_root_override="/somewhere/else"
        )
        ok, diag = check_link(destino, None)
        assert ok is False
        assert "destination_root" in diag

    def test_coherent_link_passes(self, tmp_path):
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        ok, diag = check_link(destino, None)
        assert ok is True
        assert "coherent" in diag

    def test_nonexistent_motor_root_fails_at_link(self, tmp_path):
        # A motor_root that does not exist on disk is a config error caught at
        # the link check, not degraded into the pre-push gate.
        destino = _seed_destino(tmp_path, motor_root=tmp_path / "no_such_motor")
        ok, diag = check_link(destino, None)
        assert ok is False
        assert "does not exist on disk" in diag

    def test_nonexistent_motor_root_maps_to_exit_3(self, tmp_path, monkeypatch):
        # End-to-end: the wrapper returns EXIT_CONFIG_ERROR (3), honoring its own
        # exit-code contract, instead of EXIT_CHECK_FAILED from the gate.
        destino = _seed_destino(tmp_path, motor_root=tmp_path / "no_such_motor")
        called = {"gate": False}

        def _gate(argv):
            called["gate"] = True
            return 0

        monkeypatch.setattr(wrapper, "publish_ready_main", _gate)
        rc = run_integration(destino, None, audit_publication=False)
        assert rc == EXIT_CONFIG_ERROR
        assert called["gate"] is False  # short-circuits before the gate.


class TestCheckAuthority:
    """check_destination_authority logic. find_all_agent_dirs excludes any path
    containing tests/test_runtime/factory by design, so under tmp_path (which is
    under tests/sandbox) we stub it to return the intended copies and exercise
    OUR filtering (canonical present, backups excluded, split-brain)."""

    def test_missing_collab_fails_closed(self, tmp_path):
        # A destino dir with no .agent/collaboration at all (no stub needed).
        empty = tmp_path / "empty"
        empty.mkdir()
        ok, diag = check_destination_authority(empty)
        assert ok is False
        assert "not found" in diag

    def test_no_workplan_is_not_authority(self, tmp_path, monkeypatch):
        destino = _seed_destino(tmp_path, motor_root=tmp_path, with_workplan=False)
        # No work_plan.md -> find_all_agent_dirs returns nothing for it.
        monkeypatch.setattr(wrapper, "find_all_agent_dirs", lambda root: {})
        ok, diag = check_destination_authority(destino)
        assert ok is False
        assert "not an active authority" in diag

    def test_canonical_authority_passes(self, tmp_path, monkeypatch):
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        canonical = str(destino / ".agent" / "collaboration")
        monkeypatch.setattr(
            wrapper, "find_all_agent_dirs", lambda root: {canonical: "WOT-2026-008f"}
        )
        ok, diag = check_destination_authority(destino)
        assert ok is True
        assert "single canonical authority" in diag

    def test_backup_copies_are_not_split_brain(self, tmp_path, monkeypatch):
        # A backup snapshot copy must NOT trigger split-brain.
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        canonical = str(destino / ".agent" / "collaboration")
        backup = str(
            destino / ".agent" / "backups" / "snap" / ".agent" / "collaboration"
        )
        monkeypatch.setattr(
            wrapper,
            "find_all_agent_dirs",
            lambda root: {canonical: "WOT-2026-008f", backup: "WOT-2026-001a"},
        )
        ok, diag = check_destination_authority(destino)
        assert ok is True, diag

    def test_real_split_brain_fails(self, tmp_path, monkeypatch):
        # A non-backup, non-test divergent copy IS a split-brain.
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        canonical = str(destino / ".agent" / "collaboration")
        # A divergent path that is neither a test fixture nor a backup. Use a
        # forward-slash path with no "test"/"backup" token so detect_legacy_copies
        # keeps it and our filter does not drop it.
        other = "C:/other_project/.agent/collaboration"
        monkeypatch.setattr(
            wrapper,
            "find_all_agent_dirs",
            lambda root: {canonical: "WOT-2026-008f", other: "WOT-2026-999z"},
        )
        ok, diag = check_destination_authority(destino)
        assert ok is False
        assert "split-brain" in diag


class TestRunIntegrationDelegation:
    """The wrapper propagates the pre-push gate exit code; build the rest green."""

    def _green_link_and_authority(self, tmp_path, monkeypatch):
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        # check_link / context use the real fixture (green). Authority is stubbed
        # green because find_all_agent_dirs excludes paths under tests/.
        monkeypatch.setattr(
            wrapper,
            "check_destination_authority",
            lambda project_root: (True, "[AUTHORITY] ok"),
        )
        return destino

    def test_publish_ready_failure_propagates(self, tmp_path, monkeypatch):
        destino = self._green_link_and_authority(tmp_path, monkeypatch)
        # Stub the delegated pre-push gate to report validate errors (rc=1).
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 1)
        rc = run_integration(destino, None, audit_publication=False)
        assert rc == EXIT_CHECK_FAILED

    def test_status_not_publishable_maps_to_exit_2(self, tmp_path, monkeypatch):
        destino = self._green_link_and_authority(tmp_path, monkeypatch)
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 2)
        rc = run_integration(destino, None, audit_publication=False)
        assert rc == EXIT_STATUS_NOT_PUBLISHABLE

    def test_config_error_propagates(self, tmp_path, monkeypatch):
        destino = self._green_link_and_authority(tmp_path, monkeypatch)
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 3)
        rc = run_integration(destino, None, audit_publication=False)
        assert rc == EXIT_CHECK_FAILED

    def test_all_green_returns_ok(self, tmp_path, monkeypatch):
        destino = self._green_link_and_authority(tmp_path, monkeypatch)
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 0)
        rc = run_integration(destino, None, audit_publication=False)
        assert rc == EXIT_OK

    def test_broken_link_short_circuits_before_gate(self, tmp_path, monkeypatch):
        destino = _seed_destino(tmp_path, motor_root=tmp_path, with_link=False)
        called = {"gate": False}

        def _should_not_run(argv):
            called["gate"] = True
            return 0

        monkeypatch.setattr(wrapper, "publish_ready_main", _should_not_run)
        rc = run_integration(destino, None, audit_publication=False)
        assert rc == EXIT_CONFIG_ERROR
        assert called["gate"] is False  # link failure short-circuits.


class TestPublicationAuditOptIn:
    """The first-publication audit runs ONLY with the explicit flag."""

    @pytest.fixture(autouse=True)
    def _green_authority(self, monkeypatch):
        # Authority stubbed green (find_all_agent_dirs excludes tests/ paths).
        monkeypatch.setattr(
            wrapper,
            "check_destination_authority",
            lambda project_root: (True, "[AUTHORITY] ok"),
        )

    def test_audit_not_run_by_default(self, tmp_path, monkeypatch):
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 0)
        called = {"audit": False}

        def _spy(motor_root):
            called["audit"] = True
            return True, "[AUDIT] clean"

        monkeypatch.setattr(wrapper, "run_publication_audit", _spy)
        rc = run_integration(destino, None, audit_publication=False)
        assert rc == EXIT_OK
        assert called["audit"] is False

    def test_audit_runs_with_flag(self, tmp_path, monkeypatch):
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 0)
        called = {"audit": False}

        def _spy(motor_root):
            called["audit"] = True
            return True, "[AUDIT] clean"

        monkeypatch.setattr(wrapper, "run_publication_audit", _spy)
        rc = run_integration(destino, None, audit_publication=True)
        assert rc == EXIT_OK
        assert called["audit"] is True

    def test_audit_finding_fails_closed(self, tmp_path, monkeypatch):
        destino = _seed_destino(tmp_path, motor_root=tmp_path)
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 0)
        monkeypatch.setattr(
            wrapper,
            "run_publication_audit",
            lambda motor_root: (False, "[AUDIT] secret found"),
        )
        rc = run_integration(destino, None, audit_publication=True)
        assert rc == EXIT_CHECK_FAILED


class TestPublicationAuditVerdict:
    """run_publication_audit must honor the manifest verdict, not just secrets."""

    def test_clean_verdict_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wrapper,
            "build_manifest",
            lambda repo_root, scan_history=True, out_path=None: {
                "verdict": "LISTO_PARA_PUBLICAR",
                "tree_secret_scan": {"findings": []},
                "history_secret_scan": {"findings": []},
                "blocked_reasons": [],
            },
        )
        ok, diag = run_publication_audit(tmp_path)
        assert ok is True
        assert "clean" in diag

    def test_redactions_verdict_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wrapper,
            "build_manifest",
            lambda repo_root, scan_history=True, out_path=None: {
                "verdict": "LISTO_CON_REDACTIONS",
                "tree_secret_scan": {"findings": []},
                "history_secret_scan": {"findings": []},
                "blocked_reasons": [],
            },
        )
        ok, _ = run_publication_audit(tmp_path)
        assert ok is True

    def test_non_secret_blocker_fails(self, tmp_path, monkeypatch):
        # The KEY case: no secrets, but verdict is non-publishable (e.g. motor
        # root guard). The old code returned "clean"; now it must fail.
        monkeypatch.setattr(
            wrapper,
            "build_manifest",
            lambda repo_root, scan_history=True, out_path=None: {
                "verdict": "NO_ACEPTAR_TODAVIA",
                "tree_secret_scan": {"findings": []},
                "history_secret_scan": {"findings": []},
                "blocked_reasons": [{"code": "MOTOR_ROOT_PUBLICATION_GUARD"}],
            },
        )
        ok, diag = run_publication_audit(tmp_path)
        assert ok is False
        assert "NO_ACEPTAR_TODAVIA" in diag
        assert "MOTOR_ROOT_PUBLICATION_GUARD" in diag

    def test_secret_finding_still_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wrapper,
            "build_manifest",
            lambda repo_root, scan_history=True, out_path=None: {
                "verdict": "BLOQUEADO_POR_SECRETO",
                "tree_secret_scan": {"findings": [{"path": "x"}]},
                "history_secret_scan": {"findings": []},
                "blocked_reasons": [{"code": "BLOQUEADO_POR_SECRETO"}],
            },
        )
        ok, diag = run_publication_audit(tmp_path)
        assert ok is False
        assert "secrets(tree=1" in diag


class TestMainCLI:
    def test_missing_project_root_is_config_error(self, tmp_path):
        rc = main(["--project-root", str(tmp_path / "nope")])
        assert rc == EXIT_CONFIG_ERROR

    def test_regression_red_green(self, tmp_path, monkeypatch):
        """Red->green: a broken link yields config error; a coherent fixture with
        a green delegated gate yields OK. Same wrapper, opposite outcomes."""
        monkeypatch.setattr(wrapper, "publish_ready_main", lambda argv: 0)
        monkeypatch.setattr(
            wrapper,
            "check_destination_authority",
            lambda project_root: (True, "[AUTHORITY] ok"),
        )
        # RED: broken link short-circuits to config error.
        broken = _seed_destino(tmp_path / "r", motor_root=tmp_path, with_link=False)
        assert run_integration(broken, None, audit_publication=False) == (
            EXIT_CONFIG_ERROR
        )
        # GREEN: coherent fixture with green delegated gate.
        good = _seed_destino(tmp_path / "g", motor_root=tmp_path)
        assert run_integration(good, None, audit_publication=False) == EXIT_OK
