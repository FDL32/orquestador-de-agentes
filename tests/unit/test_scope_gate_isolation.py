"""Tests for reciprocal isolation guards (WOT-2026-009c).

Verifica que check_cross_root_contamination detecta contaminacion productiva
en el repo contrario y que superficies operativas excluidas no generan falsos
positivos. Tests bidireccionales: motor->destino y destino->motor.

Barrera: cada test demuestra que la funcion distingue productive vs operational
con un run_fn stub controlado que simula git status --porcelain -z.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import scope_gate  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_fn(porcelain_output: str):
    """Return a run_fn stub that returns the given porcelain output."""

    def run_fn(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = porcelain_output
        return result

    return run_fn


def _porcelain(*paths: str) -> str:
    """Build git status --porcelain -z output for modified files."""
    return "\0".join(f" M {p}" for p in paths) + ("\0" if paths else "")


_MOTOR_ROOT = Path("/fake/motor")
_DESTINO_ROOT = Path("/fake/destino")

# Operational file that should be in the exclude set
_OP_FILE = str(
    (_DESTINO_ROOT / ".agent" / "collaboration" / "execution_log.md").resolve()
)
_OP_FILE_MOTOR = str(
    (_MOTOR_ROOT / ".agent" / "collaboration" / "execution_log.md").resolve()
)

# Productive (non-operational) files
_PROD_FILE_DESTINO = str((_DESTINO_ROOT / "src" / "app.py").resolve())
_PROD_FILE_MOTOR = str((_MOTOR_ROOT / ".agent" / "scope_gate.py").resolve())


def _destino_exclude():
    """Minimal exclude set for destino root."""
    return {_OP_FILE}


def _motor_exclude():
    """Minimal exclude set for motor root."""
    return {_OP_FILE_MOTOR}


class TestCheckCrossRootContamination:
    """Unit tests for scope_gate.check_cross_root_contamination."""

    def test_no_changes_returns_empty(self, tmp_path):
        """No git changes -> both sets empty."""
        result = scope_gate.check_cross_root_contamination(
            other_root=tmp_path,
            other_exclude=set(),
            run_fn=_make_run_fn(""),
        )
        assert result["productive"] == set()
        assert result["operational"] == set()

    def test_productive_file_in_destino_detected(self, tmp_path):
        """A productive file (not in exclude) is classified as productive."""
        prod_abs = str((tmp_path / "src" / "app.py").resolve())
        porcelain = " M src/app.py\0"
        result = scope_gate.check_cross_root_contamination(
            other_root=tmp_path,
            other_exclude=set(),
            run_fn=_make_run_fn(porcelain),
        )
        assert prod_abs in result["productive"]
        assert result["operational"] == set()

    def test_operational_file_not_in_productive(self, tmp_path):
        """A file in other_exclude is classified as operational, not productive."""
        op_abs = str(
            (tmp_path / ".agent" / "collaboration" / "execution_log.md").resolve()
        )
        porcelain = " M .agent/collaboration/execution_log.md\0"
        result = scope_gate.check_cross_root_contamination(
            other_root=tmp_path,
            other_exclude={op_abs},
            run_fn=_make_run_fn(porcelain),
        )
        assert result["productive"] == set()
        assert op_abs in result["operational"]

    def test_mixed_productive_and_operational(self, tmp_path):
        """Both types present: correctly separated."""
        op_abs = str((tmp_path / ".agent" / "collaboration" / "STATE.md").resolve())
        prod_abs = str((tmp_path / "scripts" / "new_tool.py").resolve())
        porcelain = " M .agent/collaboration/STATE.md\0 M scripts/new_tool.py\0"
        result = scope_gate.check_cross_root_contamination(
            other_root=tmp_path,
            other_exclude={op_abs},
            run_fn=_make_run_fn(porcelain),
        )
        assert prod_abs in result["productive"]
        assert op_abs in result["operational"]
        assert op_abs not in result["productive"]

    def test_run_fn_error_returns_empty(self, tmp_path):
        """If git is unavailable (FileNotFoundError), returns empty sets."""

        def broken_run_fn(cmd, **kwargs):
            raise FileNotFoundError("git not found")

        result = scope_gate.check_cross_root_contamination(
            other_root=tmp_path,
            other_exclude=set(),
            run_fn=broken_run_fn,
        )
        assert result["productive"] == set()
        assert result["operational"] == set()

    def test_bidirectional_motor_to_destino(self, tmp_path):
        """Motor-authority ticket: productive file in destino is detected."""
        destino = tmp_path / "destino"
        destino.mkdir()
        prod_abs = str((destino / "src" / "feature.py").resolve())
        porcelain = " M src/feature.py\0"
        result = scope_gate.check_cross_root_contamination(
            other_root=destino,
            other_exclude=set(),
            run_fn=_make_run_fn(porcelain),
        )
        assert prod_abs in result["productive"]

    def test_bidirectional_destino_to_motor(self, tmp_path):
        """Destino-authority ticket: productive file in motor is detected."""
        motor = tmp_path / "motor"
        motor.mkdir()
        prod_abs = str((motor / ".agent" / "scope_gate.py").resolve())
        porcelain = " M .agent/scope_gate.py\0"
        result = scope_gate.check_cross_root_contamination(
            other_root=motor,
            other_exclude=set(),
            run_fn=_make_run_fn(porcelain),
        )
        assert prod_abs in result["productive"]

    def test_operational_only_does_not_block(self, tmp_path):
        """Only operational files in other root -> productive is empty (no block)."""
        op_abs = str(
            (tmp_path / ".agent" / "runtime" / "events" / "events.jsonl").resolve()
        )
        porcelain = " M .agent/runtime/events/events.jsonl\0"
        result = scope_gate.check_cross_root_contamination(
            other_root=tmp_path,
            other_exclude={op_abs},
            run_fn=_make_run_fn(porcelain),
        )
        assert result["productive"] == set()
        assert op_abs in result["operational"]


class TestExcludeFilesSessionScratch:
    """`.session/` must be excluded like .agent/collaboration/.

    Measured 2026-10-12: a pre-existing, untracked `.session/external_review/`
    in the motor (unrelated to the ticket being handed off) made
    `exclude_files()` omit it from the exclude set, so
    `check_cross_root_contamination` classified it as "productive" and
    `--mark-ready` failed with HANDOFF_IMPOSSIBLE for every repo_destino
    ticket, regardless of what that ticket actually touched. Escalated via
    Redes_Sociales repo_destino's own backlog_inbox
    (FP-20261012-escalado-redes-sociales-cross-root-session), the correct
    mailbox for that destino's findings.
    """

    def test_session_scratch_untracked_file_is_excluded(self, tmp_path):
        """A file under <root>/.session/ must land in `excluded`, not productive."""
        collab = tmp_path / ".agent" / "collaboration"
        agent_dir = tmp_path / ".agent"
        context_dir = agent_dir / "context"
        session_file = tmp_path / ".session" / "external_review" / "notes.md"
        session_file.parent.mkdir(parents=True)
        session_file.write_text("scratch", encoding="utf-8")

        excluded = scope_gate.exclude_files(
            collab_dir=collab, agent_dir=agent_dir, context_dir=context_dir
        )

        assert str(session_file.resolve()) in excluded
        assert str((tmp_path / ".session").resolve()) in excluded

    def test_session_scratch_feeds_check_cross_root_contamination_as_operational(
        self, tmp_path
    ):
        """End-to-end: exclude_files() output makes check_cross_root_contamination
        classify .session/ content as operational, not productive (mutation check:
        BEFORE the fix, `other_exclude` from exclude_files() did not contain the
        .session/ path, so this same assertion failed with the file in
        `productive` instead of `operational`)."""
        collab = tmp_path / ".agent" / "collaboration"
        agent_dir = tmp_path / ".agent"
        context_dir = agent_dir / "context"
        session_rel = ".session/external_review/notes.md"
        session_file = tmp_path / ".session" / "external_review" / "notes.md"
        session_file.parent.mkdir(parents=True)
        session_file.write_text("scratch", encoding="utf-8")

        other_exclude = scope_gate.exclude_files(
            collab_dir=collab, agent_dir=agent_dir, context_dir=context_dir
        )
        porcelain = f" M {session_rel}\0"
        result = scope_gate.check_cross_root_contamination(
            other_root=tmp_path,
            other_exclude=other_exclude,
            run_fn=_make_run_fn(porcelain),
        )

        session_abs = str((tmp_path / session_rel).resolve())
        assert session_abs not in result["productive"]
        assert session_abs in result["operational"]

    def test_no_session_dir_does_not_crash(self, tmp_path):
        """exclude_files() must not require .session/ to exist."""
        collab = tmp_path / ".agent" / "collaboration"
        agent_dir = tmp_path / ".agent"
        context_dir = agent_dir / "context"

        excluded = scope_gate.exclude_files(
            collab_dir=collab, agent_dir=agent_dir, context_dir=context_dir
        )

        assert str((tmp_path / ".session").resolve()) not in excluded
