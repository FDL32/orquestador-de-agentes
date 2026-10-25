"""Tests WOT-2026-026o: censo read-only + reparacion opt-in de seeds legacy."""

from __future__ import annotations

from pathlib import Path

from scripts import census_destination_contracts as cdc


def _make_destino(root: Path, name: str, contracts_text: str | None) -> Path:
    dest = root / name
    (dest / ".agent" / "config").mkdir(parents=True, exist_ok=True)
    (dest / ".agent" / "config" / "motor_destination_link.json").write_text(
        "{}", encoding="utf-8"
    )
    if contracts_text is not None:
        contracts = dest / ".agent" / "planning"
        contracts.mkdir(parents=True, exist_ok=True)
        (contracts / "ticket_contracts.md").write_text(contracts_text, encoding="utf-8")
    return dest


def _dest_dirs(root: Path) -> set[str]:
    return {
        p.name
        for p in root.iterdir()
        if p.is_dir()
        and (p / ".agent" / "config" / "motor_destination_link.json").is_file()
    }


SEED = (
    "## MIGRACION DESDE repo_motor (WOT-2026-024h, DEC-024H-001)\n"
    "## WOT-2026-021k\nwaiver de 021k (PROTEGIDO, NON-GOAL)\n"
    "## WOT-2026-023r\ncontrato r\n"
    "## WOT-2026-023s\ncontrato s\n"
)


def test_026o_census_lists_seed_ids(tmp_path: Path) -> None:
    """DoD(c) mutation lado positivo: destino con contrato del motor -> el
    censo lo detecta y marca los seed ids."""
    _make_destino(tmp_path, "con-seed", SEED)
    results = cdc.census_destinations(tmp_path)
    entry = next(e for e in results if e["destino"] == "con-seed")
    assert entry["seed_ids"] == ["WOT-2026-021k", "WOT-2026-023r", "WOT-2026-023s"]


def test_026o_census_omits_destino_sin_seed(tmp_path: Path) -> None:
    """DoD(c) mutation lado negativo: sin contratos del motor -> no aparece
    marcado como seed (aunque tenga otros contratos propios)."""
    _make_destino(
        tmp_path,
        "sin-seed",
        "## WOT-2026-999z\ncontrato que el DESTINO escribio\n",
    )
    results = cdc.census_destinations(tmp_path)
    entry = next(e for e in results if e["destino"] == "sin-seed")
    assert entry["seed_ids"] == []
    assert "WOT-2026-999z" in entry["ids"]


def test_026o_census_is_read_only(tmp_path: Path) -> None:
    """DoD(a): el censo no escribe NADA (compara arbol completo antes/despues)."""

    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*")
            if p.is_file()
        }

    _make_destino(tmp_path, "d1", SEED)
    _make_destino(tmp_path, "d2", None)
    before = snapshot(tmp_path)
    cdc.census_destinations(tmp_path)
    assert snapshot(tmp_path) == before


def test_026o_repair_removes_only_seed_keeps_destination_contracts(
    tmp_path: Path,
) -> None:
    """DoD(b): reparacion opt-in retira SOLO 023r/023s; 021k (waiver) y los
    contratos del destino quedan; deja backup verificable."""
    dest = _make_destino(tmp_path, "repo", SEED + "## WOT-2026-999z\npropio\n")
    backup_dir = tmp_path / "backups"
    code, removed, err = cdc.repair_destination(dest, backup_dir)
    assert (code, removed, err) == (0, ["WOT-2026-023r", "WOT-2026-023s"], None)
    text = (dest / ".agent" / "planning" / "ticket_contracts.md").read_text(
        encoding="utf-8"
    )
    assert "WOT-2026-021k" in text and "PROTEGIDO" in text
    assert "WOT-2026-023r" not in text and "WOT-2026-023s" not in text
    assert "WOT-2026-999z" in text
    backups = list(backup_dir.glob("ticket_contracts.md.*.bak"))
    assert len(backups) == 1
    assert "contrato r" in backups[0].read_text(encoding="utf-8")


def test_026o_repair_is_idempotent(tmp_path: Path) -> None:
    """DoD(b): segunda pasada = no-op, sin reescritura del fichero."""
    dest = _make_destino(tmp_path, "repo", SEED)
    backup_dir = tmp_path / "backups"
    cdc.repair_destination(dest, backup_dir)
    after_first = (dest / ".agent" / "planning" / "ticket_contracts.md").read_text(
        encoding="utf-8"
    )
    mtime_first = (
        (dest / ".agent" / "planning" / "ticket_contracts.md").stat().st_mtime_ns
    )
    code, removed, err = cdc.repair_destination(dest, backup_dir)
    assert (code, removed, err) == (0, [], None)
    assert (dest / ".agent" / "planning" / "ticket_contracts.md").read_text(
        encoding="utf-8"
    ) == after_first
    assert (
        dest / ".agent" / "planning" / "ticket_contracts.md"
    ).stat().st_mtime_ns == mtime_first


def test_026o_repair_requires_backup_dir(tmp_path: Path) -> None:
    """Fail-closed: sin --backup-dir no se toca nada."""
    dest = _make_destino(tmp_path, "repo", SEED)
    code, removed, err = cdc.repair_destination(dest, None)  # type: ignore[arg-type]
    assert code == 1
    assert removed == []
    assert err is not None and "backup" in err.lower()
    # El fichero sigue intacto (el backup_dir None hizo raise antes de leer? no:
    # la precondicion del CLI lo bloquea; aqui el helper exige backup_dir).
    assert "WOT-2026-023r" in (
        dest / ".agent" / "planning" / "ticket_contracts.md"
    ).read_text(encoding="utf-8")


def test_026o_repair_missing_contracts_file_fails_clean(tmp_path: Path) -> None:
    dest = _make_destino(tmp_path, "vacio", None)
    code, removed, err = cdc.repair_destination(dest, tmp_path / "b")
    assert code == 1
    assert removed == []
    assert err is not None


def test_026o_cli_repair_requires_dest_and_backup(tmp_path: Path, capsys) -> None:
    assert cdc.main(["--repair", "--dest", str(tmp_path)]) == 1
    assert "--backup-dir" in capsys.readouterr().err


def test_026o_census_skips_dirs_without_link(tmp_path: Path) -> None:
    """Sin motor_destination_link.json no es un destino del censo."""
    (tmp_path / "no-destino").mkdir()
    (tmp_path / "no-destino" / "otro").mkdir(parents=True)
    assert _dest_dirs(tmp_path) == set()
    assert cdc.census_destinations(tmp_path) == []


def test_026o_cli_census_json_and_table(tmp_path: Path, capsys) -> None:
    _make_destino(tmp_path, "d1", SEED)
    assert cdc.main(["--workspaces-root", str(tmp_path), "--json"]) == 0
    import json

    data = json.loads(capsys.readouterr().out)
    assert data[0]["destino"] == "d1"
    assert cdc.main(["--workspaces-root", str(tmp_path)]) == 0
    assert "d1" in capsys.readouterr().out


def test_026o_r2_backup_sha_verifiable_con_crlf(tmp_path: Path) -> None:
    """Ronda 2 (hallazgo Codex): el sha del nombre del backup debe ser el de
    los BYTES originales; con CRLF, read_text normalizaba y el hash no
    verificaba contra el fichero .bak."""
    import hashlib

    dest = _make_destino(
        tmp_path,
        "crlf",
        SEED.replace("\n", "\r\n"),
    )
    backup_dir = tmp_path / "b"
    code, _removed, err = cdc.repair_destination(dest, backup_dir)
    assert (code, err) == (0, None)
    backup = next(backup_dir.glob("ticket_contracts.md.*.bak"))
    raw = backup.read_bytes()
    expected = hashlib.sha256(raw).hexdigest()[:8]
    assert expected in backup.name, "sha del backup no verificable (CRLF)"


def test_026o_r2_destino_autor_con_id_de_seed_se_conserva(tmp_path: Path) -> None:
    """Ronda 2 (hallazgo Codex): un contrato del DESTINO con un id del seed
    pero SIN marca de origen se CONSERVA y se nombra (nunca borrado)."""
    dest = _make_destino(
        tmp_path,
        "propio",
        "## WOT-2026-023r\ncontrato que el DESTINO escribio con este id\n",
    )
    backup_dir = tmp_path / "b"
    code, removed, _err = cdc.repair_destination(dest, backup_dir)
    assert code == 0
    assert removed == []  # nada retirado: falta la marca de origen
    text = (dest / ".agent" / "planning" / "ticket_contracts.md").read_text(
        encoding="utf-8"
    )
    assert "contrato que el DESTINO escribio" in text


def test_026o_r2_split_casa_contrato_header_y_eof_sin_salto(tmp_path: Path) -> None:
    """Ronda 2 (hallazgo Codex): `## Contrato WOT-2026-023r` y EOF sin salto
    final tambien se retiran (deteccion y reparacion alineadas)."""
    text = (
        "## Contrato WOT-2026-023r -- repo_motor\ncontenido r\n"
        "## Contrato WOT-2026-023s -- repo_motor\ncontenido s"
    )
    new_text, removed, kept = cdc._split_seed_sections(text, cdc.REPAIR_DEFAULT_IDS)
    assert removed == ["WOT-2026-023r", "WOT-2026-023s"]
    assert kept == []
    assert "contenido r" not in new_text and "contenido s" not in new_text
    assert new_text == ""
