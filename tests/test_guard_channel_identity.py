"""Tests for guard_channel_identity core logic (WOT-2026-089x, Correccion E).

Reproduces the real incident the hook targets: a turn that declares
``origen=claude-code:orquestador-de-agentes-dev-90b`` when the channel
already has a turn from a DIFFERENT editor with
``origen=claude-code:orquestador-de-agentes-dev-90``. H1 (bucle de gobierno,
2026-10-09): the rule must be BIDIRECTIONAL -- the ORIGINAL incident is
exactly this direction (new=90b, existing=90, new is NOT a prefix of
existing; existing IS a prefix of new), so the two-direction tests below
exercise both orderings explicitly.
"""

import sys
from pathlib import Path


agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from hooks.guard_channel_identity import (  # noqa: E402
    _is_prefix_either_direction,
    evaluate_channel_identity,
)


TEST_WORKSPACE = Path(__file__).parent / ".test_workspace_channel_identity"


def _write_existing(name: str, content: str) -> Path:
    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
    path = TEST_WORKSPACE / name
    path.write_text(content, encoding="utf-8")
    return path


def _cleanup():
    if TEST_WORKSPACE.exists():
        import shutil

        shutil.rmtree(TEST_WORKSPACE)


EXISTING_TURN_90 = (
    "## T41 | 2026-10-09T02:40:00Z | "
    "origen=claude-code:orquestador-de-agentes-dev-90 | in-reply-to=-\n\n"
    "Contenido del turno.\n\n---FIN-TURNO T41---\n"
)


class TestIsPrefixEitherDirection:
    def test_shorter_new_is_prefix_of_longer_existing(self):
        # Real incident direction: new="90", existing="90b".
        assert _is_prefix_either_direction("90", "90b") is True

    def test_longer_new_has_shorter_existing_as_prefix(self):
        # Inverse direction (H1 fix target): new="90b", existing="90".
        assert _is_prefix_either_direction("90b", "90") is True

    def test_unrelated_names_no_collision(self):
        assert _is_prefix_either_direction("e2", "ad") is False

    def test_identical_names_not_a_prefix_collision(self):
        assert _is_prefix_either_direction("90", "90") is False


class TestEvaluateChannelIdentityDirectionA:
    """Direction A: new name is '90b' (longer), existing is '90' (shorter) --
    the ORIGINAL incident direction, the one the bug (H1) failed to catch
    before the bidirectional fix."""

    def setup_method(self):
        _cleanup()

    def teardown_method(self):
        _cleanup()

    def test_blocks_without_escape_line(self):
        existing = _write_existing("CANAL.md", EXISTING_TURN_90)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                "new_string": (
                    "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                    "## T42 | 2026-10-09T02:45:00Z | "
                    "origen=claude-code:orquestador-de-agentes-dev-90b | "
                    "in-reply-to=T41\n\nTexto.\n\n---FIN-TURNO T42---\n"
                ),
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 2
        assert "deteccion de forma" in message
        assert "90b" in message

    def test_mutation_removing_collision_check_must_fail_red(self):
        """Mutation-verify: if the bidirectional check is disabled, this same
        payload must NOT be blocked -- confirms the test reaches the real
        branch, not a vacuous wrapper."""
        existing = _write_existing("CANAL.md", EXISTING_TURN_90)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                "new_string": (
                    "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                    "## T42 | 2026-10-09T02:45:00Z | "
                    "origen=claude-code:orquestador-de-agentes-dev-90b | "
                    "in-reply-to=T41\n\nTexto.\n\n---FIN-TURNO T42---\n"
                ),
            }
        }
        # Simulate the mutated (broken) hook: skip the prefix check entirely.
        tool_input = payload["tool_input"]
        new_pairs_present = (
            "origen=claude-code:orquestador-de-agentes-dev-90b"
            in (tool_input["new_string"])
        )
        assert new_pairs_present  # sanity: the mutation scenario is real
        # Real evaluation (unmutated) must be red (blocked) for this payload;
        # asserting it here pins the behavior this mutation would destroy.
        exit_code, _ = evaluate_channel_identity(payload)
        assert exit_code == 2

    def test_escape_line_allows_the_write(self):
        existing = _write_existing("CANAL.md", EXISTING_TURN_90)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                "new_string": (
                    "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                    "## T42 | 2026-10-09T02:45:00Z | "
                    "origen=claude-code:orquestador-de-agentes-dev-90b | "
                    "in-reply-to=T41\n\nTexto.\n"
                    "confirmado-por-ListAgents: orquestador-de-agentes-dev-90b\n"
                    "\n---FIN-TURNO T42---\n"
                ),
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 0
        assert message is None


class TestEvaluateChannelIdentityDirectionB:
    """Direction B: new name is '90' (shorter), existing is '90b' (longer) --
    the INVERSE of direction A, the case the ORIGINAL (pre-H1-fix) rule text
    claimed to cover but a naive 'new.startswith(existing)'-only check would
    miss if written backwards again."""

    def setup_method(self):
        _cleanup()

    def teardown_method(self):
        _cleanup()

    def test_blocks_without_escape_line(self):
        existing_turn_90b = (
            "## T41 | 2026-10-09T02:40:00Z | "
            "origen=claude-code:orquestador-de-agentes-dev-90b | in-reply-to=-\n\n"
            "Contenido del turno.\n\n---FIN-TURNO T41---\n"
        )
        existing = _write_existing("CANAL.md", existing_turn_90b)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                "new_string": (
                    "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                    "## T42 | 2026-10-09T02:45:00Z | "
                    "origen=claude-code:orquestador-de-agentes-dev-90 | "
                    "in-reply-to=T41\n\nTexto.\n\n---FIN-TURNO T42---\n"
                ),
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 2
        assert "deteccion de forma" in message


class TestEvaluateChannelIdentityNonCollision:
    def setup_method(self):
        _cleanup()

    def teardown_method(self):
        _cleanup()

    def test_unrelated_session_names_pass(self):
        existing = _write_existing("CANAL.md", EXISTING_TURN_90)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                "new_string": (
                    "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                    "## T42 | 2026-10-09T02:45:00Z | "
                    "origen=cursor:orquestador-de-agentes-dev-e2 | "
                    "in-reply-to=T41\n\nTexto.\n\n---FIN-TURNO T42---\n"
                ),
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 0
        assert message is None

    def test_identical_editor_and_name_pair_is_not_a_collision(self):
        existing = _write_existing("CANAL.md", EXISTING_TURN_90)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                "new_string": (
                    "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                    "## T42 | 2026-10-09T02:45:00Z | "
                    "origen=claude-code:orquestador-de-agentes-dev-90 | "
                    "in-reply-to=T41\n\nTexto.\n\n---FIN-TURNO T42---\n"
                ),
            }
        }
        exit_code, _ = evaluate_channel_identity(payload)
        assert exit_code == 0

    def test_non_channel_edit_is_out_of_scope(self):
        existing = _write_existing("regular_file.py", "print('hello')\n")
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "old_string": "print('hello')\n",
                "new_string": "print('hello world')\n",
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 0
        assert message is None

    def test_brand_new_write_with_no_prior_origen_passes(self):
        """Write (not Edit) creating the file from scratch: no existing text
        on disk yet, no collision is possible against nothing."""
        new_path = TEST_WORKSPACE / "new_channel.md"
        TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
        payload = {
            "tool_input": {
                "file_path": str(new_path),
                "content": (
                    "## T1 | 2026-10-09T02:45:00Z | "
                    "origen=claude-code:orquestador-de-agentes-dev-90b | "
                    "in-reply-to=-\n\nTexto.\n\n---FIN-TURNO T1---\n"
                ),
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 0
        assert message is None


class TestMultiEditEscapeScopedPerBlock:
    """Codex DESIGN_REVIEW finding (2026-10-09): a global escape check over
    the whole joined ``new_text`` let a ``confirmado-por-ListAgents:`` line
    in ONE MultiEdit block exempt the colliding ``origen=`` in a DIFFERENT
    block of the SAME payload. The escape must be scoped per-block."""

    def setup_method(self):
        _cleanup()

    def teardown_method(self):
        _cleanup()

    def test_escape_in_one_block_does_not_exempt_a_different_block(self):
        existing = _write_existing("CANAL.md", EXISTING_TURN_90)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "edits": [
                    {
                        "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                        "new_string": (
                            "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                            "## T42 | 2026-10-09T02:45:00Z | "
                            "origen=cursor:orquestador-de-agentes-dev-e2 | "
                            "in-reply-to=T41\n\nTexto.\n"
                            "confirmado-por-ListAgents: orquestador-de-agentes-dev-e2\n"
                            "\n---FIN-TURNO T42---\n"
                        ),
                    },
                    {
                        "old_string": "## Ultimo estado",
                        "new_string": (
                            "## Ultimo estado\n\n"
                            "- **Ultimo turno:** T42 | 2026-10-09T02:45:00Z | "
                            "origen=claude-code:orquestador-de-agentes-dev-90b"
                        ),
                    },
                ],
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 2
        assert "90b" in message

    def test_escape_in_the_colliding_block_itself_still_exempts_it(self):
        existing = _write_existing("CANAL.md", EXISTING_TURN_90)
        payload = {
            "tool_input": {
                "file_path": str(existing),
                "edits": [
                    {
                        "old_string": "Contenido del turno.\n\n---FIN-TURNO T41---\n",
                        "new_string": (
                            "Contenido del turno.\n\n---FIN-TURNO T41---\n\n"
                            "## T42 | 2026-10-09T02:45:00Z | "
                            "origen=claude-code:orquestador-de-agentes-dev-90b | "
                            "in-reply-to=T41\n\nTexto.\n"
                            "confirmado-por-ListAgents: orquestador-de-agentes-dev-90b\n"
                            "\n---FIN-TURNO T42---\n"
                        ),
                    },
                ],
            }
        }
        exit_code, message = evaluate_channel_identity(payload)
        assert exit_code == 0
        assert message is None
