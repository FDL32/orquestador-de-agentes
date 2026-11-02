"""Tests WOT-2026-026o: censo read-only + reparacion opt-in de seeds legacy."""

from __future__ import annotations

from pathlib import Path

import pytest
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
        "## MIGRACION DESDE repo_motor (WOT-2026-024h, DEC-024H-001)\n"
        "## Contrato WOT-2026-023r -- repo_motor\ncontenido r\n"
        "## Contrato WOT-2026-023s -- repo_motor\ncontenido s"
    )
    new_text, removed, kept = cdc._split_seed_sections(text, cdc.REPAIR_DEFAULT_IDS)
    assert removed == ["WOT-2026-023r", "WOT-2026-023s"]
    assert kept == []
    assert "contenido r" not in new_text and "contenido s" not in new_text
    assert "MIGRACION" in new_text


def test_026o_r3_sin_fallback_de_marca_local(tmp_path: Path) -> None:
    """Ronda 3 (hallazgo Codex): un titulo que cite repo_motor NO es marca de
    origen; sin el bloque MIGRACION contiguo, la seccion se CONSERVA."""
    dest = _make_destino(
        tmp_path,
        "sin-bloque",
        "## Contrato WOT-2026-023r -- repo_motor\ncontrato del destino\n",
    )
    backup_dir = tmp_path / "b"
    code, removed, _err = cdc.repair_destination(dest, backup_dir)
    assert code == 0
    assert removed == []
    assert "contrato del destino" in (
        dest / ".agent" / "planning" / "ticket_contracts.md"
    ).read_text(encoding="utf-8")


# --- WOT-2026-152j (026o-r4): marca de origen POR POSICION, fail-closed ---------

MIG = "## MIGRACION DESDE repo_motor (WOT-2026-024h, DEC-024H-001)\n\nnota\n\n"
DEST_BODY = "CONTRATO ESCRITO POR EL DESTINO"
CR = "WOT-2026-023r"
CS = "WOT-2026-023s"
CK = "WOT-2026-021k"


def _sec(title: str, body: str) -> str:
    return f"## {title}\n\n{body}\n\n"


def _contracts(dest: Path) -> Path:
    return dest / ".agent" / "planning" / "ticket_contracts.md"


def _repair(tmp_path: Path, text: str, name: str = "repo"):
    dest = _make_destino(tmp_path, name, text)
    result = cdc.repair_destination(dest, tmp_path / "bk")
    return dest, result


def test_152j_probe_destino_id_duplicado_tras_la_cadena_sobrevive(
    tmp_path: Path, capsys
) -> None:
    """DoD(1)(2): ROJO del blocker. Mismo id escrito por el destino DESPUES de
    otra seccion: se retira la 023r del motor y la del destino sobrevive."""
    text = (
        _sec("T-001 -- propio", "cuerpo 1")
        + MIG
        + _sec(CK, "seed 021k")
        + _sec(CR, "seed r DEL MOTOR")
        + _sec(CS, "seed s DEL MOTOR")
        + _sec("T-002 -- otro", "cuerpo 2")
        + _sec(CR, DEST_BODY)
    )
    dest, (code, removed, err) = _repair(tmp_path, text)
    assert (code, removed, err) == (0, [CR, CS], None)
    after = _contracts(dest).read_text(encoding="utf-8")
    assert DEST_BODY in after
    assert "DEL MOTOR" not in after
    assert "cuerpo 1" in after and "cuerpo 2" in after and "seed 021k" in after
    assert f"CONSERVADAS por falta de marca de origen: {CR}" in capsys.readouterr().out
    # idempotente: segunda pasada sin cambios y el contrato del destino sigue
    mtime = _contracts(dest).stat().st_mtime_ns
    assert cdc.repair_destination(dest, tmp_path / "bk") == (0, [], None)
    assert _contracts(dest).stat().st_mtime_ns == mtime
    assert DEST_BODY in _contracts(dest).read_text(encoding="utf-8")


def test_152j_cadena_contigua_legitima_retira_023r_y_023s(tmp_path: Path) -> None:
    """Control positivo: la cadena MIG+021k+023r+023s se retira (021k queda)."""
    text = MIG + _sec(CK, "seed 021k") + _sec(CR, "seed r") + _sec(CS, "seed s")
    dest, (code, removed, err) = _repair(tmp_path, text)
    assert (code, removed, err) == (0, [CR, CS], None)
    after = _contracts(dest).read_text(encoding="utf-8")
    assert "seed 021k" in after and "seed r" not in after and "seed s" not in after


def test_152j_id_de_seed_antes_del_bloque_migracion_se_conserva(
    tmp_path: Path,
) -> None:
    """DoD(1): el contrato del destino con id de seed ESCRITO ANTES del bloque
    MIG se conserva; solo se retira el de la cadena."""
    text = _sec(CR, DEST_BODY) + MIG + _sec(CR, "seed r DEL MOTOR")
    dest, (code, removed, _err) = _repair(tmp_path, text)
    assert (code, removed) == (0, [CR])
    after = _contracts(dest).read_text(encoding="utf-8")
    assert DEST_BODY in after and "DEL MOTOR" not in after


def test_152j_id_duplicado_dentro_de_la_cadena_conserva_ambas(
    tmp_path: Path, capsys
) -> None:
    """DoD(2): 023r repetida DENTRO de la cadena es ambigua -> se conservan las
    dos y se nombran; la 023s no ambigua si se retira."""
    text = MIG + _sec(CK, "k") + _sec(CR, "primera r") + _sec(CR, "segunda r")
    text += _sec(CS, "seed s")
    dest, (code, removed, _err) = _repair(tmp_path, text)
    assert (code, removed) == (0, [CS])
    after = _contracts(dest).read_text(encoding="utf-8")
    assert "primera r" in after and "segunda r" in after
    assert CR in capsys.readouterr().out


@pytest.mark.parametrize(
    "mig_title",
    [
        "## MIGRACION DESDE otro_sitio (WOT-2026-024h)",
        "## nota sobre repo_motor (WOT-2026-024h)",
    ],
)
def test_152j_marca_exige_migracion_y_repo_motor(tmp_path: Path, mig_title) -> None:
    """DoD(3): la conjuncion MIGRACION y repo_motor; con solo una de las dos
    palabras la 023r se conserva (la cadena positiva ya se prueba arriba)."""
    text = f"{mig_title}\n\nnota\n\n" + _sec(CR, "seed r")
    dest, (code, removed, _err) = _repair(tmp_path, text)
    assert (code, removed) == (0, [])
    assert "seed r" in _contracts(dest).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "middle",
    [
        _sec("T-9 -- propio", "intermedio"),
        _sec(CK, "k") + _sec("T-2 -- propio", "intermedio"),
    ],
)
def test_152j_seccion_intermedia_corta_la_cadena(tmp_path: Path, middle) -> None:
    """DoD(4): una seccion que no es del seed corta la cadena; la 023r de
    detras no hereda la marca y se conserva."""
    text = MIG + middle + _sec(CR, DEST_BODY)
    dest, (code, removed, _err) = _repair(tmp_path, text)
    assert (code, removed) == (0, [])
    assert DEST_BODY in _contracts(dest).read_text(encoding="utf-8")


def test_152j_segundo_bloque_migracion_no_hereda_marca(tmp_path: Path, capsys) -> None:
    """LIMITE declarado: solo cuenta el primer bloque MIG; el segundo grupo se
    conserva y se nombra."""
    text = MIG + _sec(CR, "grupo 1") + MIG + _sec(CS, "grupo 2")
    dest, (code, removed, _err) = _repair(tmp_path, text)
    assert (code, removed) == (0, [CR])
    after = _contracts(dest).read_text(encoding="utf-8")
    assert "grupo 2" in after and "grupo 1" not in after
    assert CS in capsys.readouterr().out


def test_152j_crlf_retira_la_cadena_y_conserva_bytes_del_destino(
    tmp_path: Path,
) -> None:
    text = (
        MIG + _sec(CR, "seed r") + _sec("T-2 -- propio", "x") + _sec(CR, DEST_BODY)
    ).replace("\n", "\r\n")
    dest = _make_destino(tmp_path, "crlf", "")
    _contracts(dest).write_bytes(text.encode("utf-8"))
    code, removed, _err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (0, [CR])
    after = _contracts(dest).read_bytes()
    assert DEST_BODY.encode() + b"\r\n" in after and b"seed r" not in after


def test_152j_bom_en_el_primer_header_conserva_todo(tmp_path: Path) -> None:
    """Fail-closed: con BOM el primer header no casa, no hay marca -> no-op."""
    dest = _make_destino(tmp_path, "bom", "")
    raw = ("﻿" + MIG + _sec(CR, "seed r")).encode("utf-8")
    _contracts(dest).write_bytes(raw)
    assert cdc.repair_destination(dest, tmp_path / "bk") == (0, [], None)
    assert _contracts(dest).read_bytes() == raw


@pytest.mark.parametrize("text", ["", MIG], ids=["vacio", "solo-bloque-migracion"])
def test_152j_vacio_o_solo_bloque_es_noop_sin_reescritura(
    tmp_path: Path, text: str
) -> None:
    dest = _make_destino(tmp_path, "vacio", text)
    mtime = _contracts(dest).stat().st_mtime_ns
    assert cdc.repair_destination(dest, tmp_path / "bk") == (0, [], None)
    assert _contracts(dest).stat().st_mtime_ns == mtime
    assert _contracts(dest).read_text(encoding="utf-8") == text


def test_152j_ruta_es_un_directorio_rc1_sin_backup(tmp_path: Path) -> None:
    dest = _make_destino(tmp_path, "dir", None)
    _contracts(dest).mkdir(parents=True)
    code, removed, err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (1, []) and err
    assert not (tmp_path / "bk").exists()


def test_152j_enlace_roto_rc1_sin_backup(tmp_path: Path) -> None:
    dest = _make_destino(tmp_path, "roto", None)
    _contracts(dest).parent.mkdir(parents=True, exist_ok=True)
    try:
        _contracts(dest).symlink_to(tmp_path / "no-existe.md")
    except OSError:
        pytest.skip("sin privilegio para crear symlinks")
    code, _removed, err = cdc.repair_destination(dest, tmp_path / "bk")
    assert code == 1 and err
    assert not (tmp_path / "bk").exists()


def test_152j_enlace_valido_no_se_sustituye_por_fichero(tmp_path: Path) -> None:
    """os.replace rompería el enlace: se rechaza y el destino real no cambia."""
    dest = _make_destino(tmp_path, "enlace", None)
    real = tmp_path / "real.md"
    real.write_text(MIG + _sec(CR, "seed r"), encoding="utf-8")
    _contracts(dest).parent.mkdir(parents=True, exist_ok=True)
    try:
        _contracts(dest).symlink_to(real)
    except OSError:
        pytest.skip("sin privilegio para crear symlinks")
    before = real.read_bytes()
    code, removed, err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (1, []) and err
    assert _contracts(dest).is_symlink() and real.read_bytes() == before


def test_152j_no_utf8_rc1_no_reescribe_y_deja_backup(tmp_path: Path, capsys) -> None:
    """Caso 14: bytes invalidos -> no se reescribe (errors=replace habria
    corrompido el resto con U+FFFD); el backup existe con los bytes originales."""
    raw = (MIG + _sec(CR, "seed r")).encode("utf-8") + b"\n## T-3\n\xff\xfe cuerpo\n"
    dest = _make_destino(tmp_path, "latin", "")
    _contracts(dest).write_bytes(raw)
    code, removed, err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (1, []) and err and "UTF-8" in err
    assert _contracts(dest).read_bytes() == raw
    backups = list((tmp_path / "bk").glob("ticket_contracts.md.*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == raw
    argv = ["--repair", "--dest", str(dest), "--backup-dir", str(tmp_path / "bk")]
    assert cdc.main(argv) == 1
    assert "UTF-8" in capsys.readouterr().err


def test_152j_backup_imposible_aborta_sin_escribir(tmp_path: Path) -> None:
    """(i) backup_dir es un FICHERO: mkdir falla -> rc 1 limpio, original intacto."""
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "bkfail", text)
    not_a_dir = tmp_path / "fichero"
    not_a_dir.write_text("x", encoding="utf-8")
    code, removed, err = cdc.repair_destination(dest, not_a_dir)
    assert (code, removed) == (1, []) and err and "backup" in err.lower()
    assert _contracts(dest).read_text(encoding="utf-8") == text


def test_152j_backup_con_sha_distinto_aborta_sin_escribir(
    tmp_path: Path, monkeypatch
) -> None:
    """(ii) el backup se relee: si queda truncado no se escribe el original."""
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "bksha", text)
    real_read = cdc._read_regular

    def truncating(path):
        data = real_read(path)
        return data[:-1] if data is not None and path.suffix == ".bak" else data

    monkeypatch.setattr(cdc, "_read_regular", truncating)
    code, removed, err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (1, []) and err and "sha" in err
    assert _contracts(dest).read_text(encoding="utf-8") == text


def test_152j_el_backup_existe_antes_de_la_escritura(
    tmp_path: Path, monkeypatch
) -> None:
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "orden", text)
    seen: list[bytes] = []
    real_write = cdc._write_atomic

    def spy(path: Path, data: bytes) -> None:
        backups = list((tmp_path / "bk").glob("ticket_contracts.md.*.bak"))
        seen.append(backups[0].read_bytes() if backups else b"")
        real_write(path, data)

    monkeypatch.setattr(cdc, "_write_atomic", spy)
    original = _contracts(dest).read_bytes()
    assert cdc.repair_destination(dest, tmp_path / "bk")[0] == 0
    assert seen == [original]


def test_152j_replace_fallido_deja_original_y_sin_temporal(
    tmp_path: Path, monkeypatch
) -> None:
    """(iii) si os.replace falla: rc 1, original byte a byte, sin temporal."""
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "atomic", text)

    def boom(src, dst):
        raise PermissionError("simulado")

    monkeypatch.setattr(cdc.os, "replace", boom)
    code, removed, err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (1, []) and err and "intacto" in err
    assert _contracts(dest).read_text(encoding="utf-8") == text
    assert list(_contracts(dest).parent.glob("*census-tmp")) == []


def _symlink_or_skip(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("sin privilegio para crear symlinks")


def test_152j_r2_temporal_antiguo_symlink_no_modifica_el_original(
    tmp_path: Path, monkeypatch
) -> None:
    """BLOCKER r2: el nombre de temporal ya no es previsible. Un symlink en el
    nombre antiguo apuntando al original NO debe hacer que la escritura toque el
    original antes del replace (replace fallido => original intacto)."""
    # seccion propia DETRAS de la retirada: el texto nuevo no es prefijo del viejo
    text = MIG + _sec(CR, "seed r") + _sec("T-2 -- propio", "cola del destino")
    dest = _make_destino(tmp_path, "tmplink", text)
    old_name = _contracts(dest).parent / ".ticket_contracts.md.census-tmp"
    _symlink_or_skip(old_name, _contracts(dest))
    original = _contracts(dest).read_bytes()

    def boom(src, dst):
        raise PermissionError("simulado")

    monkeypatch.setattr(cdc.os, "replace", boom)
    code, removed, err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (1, []) and err
    assert _contracts(dest).read_bytes() == original


def test_152j_r2_temporal_antiguo_symlink_resultado_correcto(tmp_path: Path) -> None:
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "tmplink2", text)
    old_name = _contracts(dest).parent / ".ticket_contracts.md.census-tmp"
    _symlink_or_skip(old_name, _contracts(dest))
    code, removed, _err = cdc.repair_destination(dest, tmp_path / "bk")
    assert (code, removed) == (0, [CR])
    assert not _contracts(dest).is_symlink()
    assert "seed r" not in _contracts(dest).read_text(encoding="utf-8")
    assert old_name.is_symlink()  # no era nuestro: ni se toca ni se borra


def test_152j_r2_replace_fallido_no_deja_ningun_temporal(
    tmp_path: Path, monkeypatch
) -> None:
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "tmpclean", text)
    before = sorted(p.name for p in _contracts(dest).parent.iterdir())

    def boom(src, dst):
        raise PermissionError("simulado")

    monkeypatch.setattr(cdc.os, "replace", boom)
    assert cdc.repair_destination(dest, tmp_path / "bk")[0] == 1
    assert sorted(p.name for p in _contracts(dest).parent.iterdir()) == before


def _backup_name(raw: bytes) -> str:
    import hashlib

    return f"ticket_contracts.md.{hashlib.sha256(raw).hexdigest()[:8]}.bak"


def test_152j_r2_backup_symlink_al_original_rc1_sin_escribir(tmp_path: Path) -> None:
    """MAJOR r2: un '<nombre>.<sha8>.bak' preexistente que es symlink al
    original no es una copia: rc 1 y el original no cambia."""
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "bklink", text)
    raw = _contracts(dest).read_bytes()
    bk = tmp_path / "bk"
    _symlink_or_skip(bk / _backup_name(raw), _contracts(dest))
    code, removed, err = cdc.repair_destination(dest, bk)
    assert (code, removed) == (1, []) and err and "backup" in err.lower()
    assert _contracts(dest).read_bytes() == raw


def test_152j_r2_backup_preexistente_distinto_o_directorio_rc1(
    tmp_path: Path,
) -> None:
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "bkdist", text)
    raw = _contracts(dest).read_bytes()
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / _backup_name(raw)).write_bytes(b"otra cosa")
    code, removed, err = cdc.repair_destination(dest, bk)
    assert (code, removed) == (1, []) and err
    assert _contracts(dest).read_bytes() == raw
    assert (bk / _backup_name(raw)).read_bytes() == b"otra cosa"
    (bk / _backup_name(raw)).unlink()
    (bk / _backup_name(raw)).mkdir()
    assert cdc.repair_destination(dest, bk)[0] == 1
    assert _contracts(dest).read_bytes() == raw


def test_152j_r2_backup_preexistente_regular_identico_se_reutiliza(
    tmp_path: Path,
) -> None:
    text = MIG + _sec(CR, "seed r")
    dest = _make_destino(tmp_path, "bkreuse", text)
    raw = _contracts(dest).read_bytes()
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / _backup_name(raw)).write_bytes(raw)
    code, removed, _err = cdc.repair_destination(dest, bk)
    assert (code, removed) == (0, [CR])
    assert (bk / _backup_name(raw)).read_bytes() == raw


def test_152j_r2_censo_raiz_no_listable_rc2_sin_traceback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    def boom(self):
        raise PermissionError("simulado")

    monkeypatch.setattr(Path, "iterdir", boom)
    assert cdc.main(["--workspaces-root", str(tmp_path)]) == 2
    assert "ERROR" in capsys.readouterr().err


def test_152j_escritura_ok_no_deja_temporal(tmp_path: Path) -> None:
    dest, (code, removed, _err) = _repair(tmp_path, MIG + _sec(CR, "seed r"))
    assert (code, removed) == (0, [CR])
    assert list(_contracts(dest).parent.iterdir()) == [_contracts(dest)]
