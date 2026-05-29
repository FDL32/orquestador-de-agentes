"""Tests for create_checkpoint.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "create_checkpoint.py"
EVENTS_FILE_PATH = Path(".agent") / "runtime" / "events" / "events.jsonl"


def init_git_repo(repo_path: Path) -> None:
    """Initialize a git repository with initial commit."""
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def tag_exists(repo_path: Path, tag_name: str) -> bool:
    """Check if a tag exists."""
    result = subprocess.run(
        ["git", "rev-parse", tag_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


class TestCreateCheckpoint:
    """Tests for create_checkpoint.py script."""

    def test_create_m3_checkpoint(self, tmp_path: Path) -> None:
        """Should create M3 checkpoint tag and emit BUILDER_MILESTONE."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--milestone",
                "M3",
                "--ticket-id",
                "WP-2026-167",
                "--project-root",
                str(repo),
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "created"
        assert output["milestone"] == "M3"
        assert output["tag"] == "checkpoint/review-WP-2026-167"
        assert "sha" in output

        # Verify tag was created
        assert tag_exists(repo, "checkpoint/review-WP-2026-167")

        # Verify BUILDER_MILESTONE event was emitted
        events_file = repo / EVENTS_FILE_PATH
        assert events_file.exists()
        content = events_file.read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n") if line]
        milestone_events = [e for e in events if e["event_type"] == "BUILDER_MILESTONE"]
        assert len(milestone_events) == 1
        assert milestone_events[0]["payload"]["milestone"] == "M3"
        assert milestone_events[0]["payload"]["tag"] == "checkpoint/review-WP-2026-167"

    def test_create_all_milestones(self, tmp_path: Path) -> None:
        """Should create all milestone types M0-M4."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        milestones = ["M0", "M1", "M2", "M3", "M4"]
        expected_tags = {
            "M0": "checkpoint/base-WP-2026-167",
            "M1": "checkpoint/design-WP-2026-167",
            "M2": "checkpoint/implementation-WP-2026-167",
            "M3": "checkpoint/review-WP-2026-167",
            "M4": "checkpoint/closed-WP-2026-167",
        }

        for milestone in milestones:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--milestone",
                    milestone,
                    "--ticket-id",
                    "WP-2026-167",
                    "--project-root",
                    str(repo),
                    "--json",
                ],
                capture_output=True,
                text=True,
                cwd=repo,
            )

            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert output["status"] == "created"
            assert output["tag"] == expected_tags[milestone]

    def test_skip_existing_tag(self, tmp_path: Path) -> None:
        """Should skip and warn if tag already exists."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Create tag manually first
        subprocess.run(
            ["git", "tag", "-a", "checkpoint/review-WP-2026-167", "-m", "Manual tag"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--milestone",
                "M3",
                "--ticket-id",
                "WP-2026-167",
                "--project-root",
                str(repo),
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "skipped"
        assert "already exists" in output["reason"]

    def test_invalid_milestone(self, tmp_path: Path) -> None:
        """Should fail with invalid milestone."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        # Use argparse which will catch invalid choices before our code runs
        # So we test by passing an invalid value
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--milestone",
                "M5",  # Invalid
                "--ticket-id",
                "WP-2026-167",
                "--project-root",
                str(repo),
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        # argparse will reject invalid milestone
        assert result.returncode != 0
        assert (
            "invalid choice" in result.stderr.lower()
            or "error" in result.stderr.lower()
        )

    def test_non_git_repo(self, tmp_path: Path) -> None:
        """Should fail when not in a git repository."""
        repo = tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--milestone",
                "M3",
                "--ticket-id",
                "WP-2026-167",
                "--project-root",
                str(repo),
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["status"] == "error"

    def test_human_readable_output(self, tmp_path: Path) -> None:
        """Should produce human-readable output without --json."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--milestone",
                "M3",
                "--ticket-id",
                "WP-2026-167",
                "--project-root",
                str(repo),
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 0
        assert "[OK]" in result.stdout
        assert "checkpoint/review-WP-2026-167" in result.stdout
        assert "SHA:" in result.stdout

    def test_buidler_milestone_event_payload(self, tmp_path: Path) -> None:
        """BUILDER_MILESTONE event should have correct payload structure."""
        repo = tmp_path / "repo"
        init_git_repo(repo)

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--milestone",
                "M3",
                "--ticket-id",
                "WP-2026-167",
                "--project-root",
                str(repo),
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )

        assert result.returncode == 0

        events_file = repo / EVENTS_FILE_PATH
        content = events_file.read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.strip().split("\n") if line]
        milestone_event = next(
            e for e in events if e["event_type"] == "BUILDER_MILESTONE"
        )

        # Verify payload structure
        payload = milestone_event["payload"]
        assert "milestone" in payload
        assert "tag" in payload
        assert "sha" in payload
        assert "description" in payload
        assert payload["milestone"] == "M3"
        assert payload["tag"] == "checkpoint/review-WP-2026-167"

        # Verify event structure — sequence_number must be assigned by EventBus
        assert milestone_event["ticket_id"] == "WP-2026-167"
        assert milestone_event["actor"] == "BUILDER"
        assert "timestamp" in milestone_event
        assert "sequence_number" in milestone_event, (
            "BUILDER_MILESTONE must be emitted via EventBus so sequence_number is assigned"
        )
        assert isinstance(milestone_event["sequence_number"], int)
