import pytest
from scripts.check_backlog_contract import bind_ticket_prefix
from scripts.check_backlog_dependency_graph import (
    check_backlog_integrity,
    parse_depends_cell,
)


@pytest.fixture
def mock_backlog_env(tmp_path):
    """Provides a synthetic backlog and archive environment."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    archive = collab / "_archive"
    archive.mkdir()

    # 1. Create archive (WOT-2026-001s and WOT-2026-002a)
    archive_file = archive / "backlog_done.md"
    archive_content = (
        "# Backlog -- historico\n\n"
        "| Baja | WOT-2026-001s | [CERRADO 2026-10-01 commit:abc123] | ... |\n"
        "| Baja | WOT-2026-002a | [CERRADO 2026-10-02 commit:def456] | ... |\n"
    )
    archive_file.write_text(archive_content, encoding="utf-8-sig")

    # 2. Create live backlog
    backlog_file = collab / "backlog.md"
    # We use the Prioridad-led format
    # Fixture rows cover the four cases this guard discriminates, in order:
    # satisfied (001s), hanging (002a, archived but not marked SATISFECHA),
    # phantom (WOT-9999-x, cited nowhere), and the negative control (no deps).
    backlog_content = (
        "# Backlog (cola viva)\n\n"
        "## Vista rapida\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
        "| Alta | WOT-2026-010a | Satisfied Task | Small | pending | WOT-2026-001s SATISFECHA 2026-10-01 | local | -\n"
        "| Media | WOT-2026-010b | Hanging Task | Medium | pending | WOT-2026-002a | local | -\n"
        "| Baja | WOT-2026-010c | Phantom Task | Small | pending | WOT-9999-x | local | -\n"
        "| Baja | WOT-2026-010d | No Deps Task | Small | pending | - | local | -\n"
    )
    backlog_file.write_text(backlog_content, encoding="utf-8-sig")

    return tmp_path


def test_parse_depends_cell_basic():
    assert parse_depends_cell("-") == {"ids": [], "satisfied_ids": [], "raw": "-"}
    assert parse_depends_cell("WOT-2026-001s") == {
        "ids": ["WOT-2026-001s"],
        "satisfied_ids": [],
        "raw": "WOT-2026-001s",
    }
    assert parse_depends_cell("WOT-2026-001s, WOT-2026-002a SATISFECHA 2026-10-01") == {
        "ids": ["WOT-2026-001s", "WOT-2026-002a"],
        "satisfied_ids": ["WOT-2026-002a"],
        "raw": "WOT-2026-001s, WOT-2026-002a SATISFECHA 2026-10-01",
    }


def test_integrity_check(mock_backlog_env, monkeypatch):
    def mock_ensure_bound(start):
        bind_ticket_prefix("WOT|WP|WT|CTL")
        return True, None

    monkeypatch.setattr(
        "scripts.check_backlog_dependency_graph.ensure_bound", mock_ensure_bound
    )

    errors = check_backlog_integrity(mock_backlog_env)

    # Should find:
    # 1. Hanging: WOT-2026-010b -> WOT-2026-002a
    # 2. Phantom: WOT-2026-010c -> WOT-9999-x
    assert any("Hanging dependency on WOT-2026-002a" in e for e in errors)
    assert any("Phantom dependency on WOT-9999-x" in e for e in errors)
    assert not any("WOT-2026-010a" in e for e in errors)
    assert not any("WOT-2026-010d" in e for e in errors)
    assert len(errors) == 2


def test_mutation_isolation_phantom(mock_backlog_env, monkeypatch):
    def mock_ensure_bound(start):
        bind_ticket_prefix("WOT|WP|WT|CTL")
        return True, None

    monkeypatch.setattr(
        "scripts.check_backlog_dependency_graph.ensure_bound", mock_ensure_bound
    )

    # 1. Only phantom present
    collab = mock_backlog_env / ".agent" / "collaboration"
    backlog_file = collab / "backlog.md"
    backlog_file.write_text(
        "# Backlog (cola viva)\n\n"
        "## Vista rapida\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
        "| Baja | WOT-2026-010p | Phantom Task | Small | pending | WOT-9999-x | local | -\n",
        encoding="utf-8-sig",
    )
    errors = check_backlog_integrity(mock_backlog_env)
    assert len(errors) == 1
    assert "Phantom" in errors[0]

    # 2. Only hanging present
    backlog_file.write_text(
        "# Backlog (cola viva)\n\n"
        "## Vista rapida\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
        "| Media | WOT-2026-010h | Hanging Task | Medium | pending | WOT-2026-002a | local | -\n",
        encoding="utf-8-sig",
    )
    errors = check_backlog_integrity(mock_backlog_env)
    assert len(errors) == 1
    assert "Hanging" in errors[0]

    # 3. Both present
    backlog_file.write_text(
        "# Backlog (cola viva)\n\n"
        "## Vista rapida\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
        "| Baja | WOT-2026-010p | Phantom Task | Small | pending | WOT-9999-x | local | -\n"
        "| Media | WOT-2026-010h | Hanging Task | Medium | pending | WOT-2026-002a | local | -\n",
        encoding="utf-8-sig",
    )
    errors = check_backlog_integrity(mock_backlog_env)
    assert len(errors) == 2


def test_negative_control(mock_backlog_env, monkeypatch):
    def mock_ensure_bound(start):
        bind_ticket_prefix("WOT|WP|WT|CTL")
        return True, None

    monkeypatch.setattr(
        "scripts.check_backlog_dependency_graph.ensure_bound", mock_ensure_bound
    )

    collab = mock_backlog_env / ".agent" / "collaboration"
    backlog_file = collab / "backlog.md"
    backlog_file.write_text(
        "# Backlog (cola viva)\n\n"
        "## Vista rapida\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
        "| Baja | WOT-2026-010d | No Deps Task | Small | pending | - | local | -\n",
        encoding="utf-8-sig",
    )

    errors = check_backlog_integrity(mock_backlog_env)
    assert len(errors) == 0
