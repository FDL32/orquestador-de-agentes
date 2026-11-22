"""Tests for scripts/check_ensemble_profile_catalog.py y refresh_ensemble_model_catalog.py.

WOT-2026-222a v4. Corrige 4 defectos medidos en P34 ronda 3 (ds H-03/H-06/H-07/H-12):
invocacion por defecto rota (ahora SIEMPRE -m), fixture que no mide sus propios
conteos, control positivo que no cubre el agents.json real, y una fecha de
expiracion fija que caducaba el test solo.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_ensemble_profile_catalog as cepc  # noqa: E402
import refresh_ensemble_model_catalog as remc  # noqa: E402


_FIXTURE = _MOTOR_ROOT / "tests" / "fixtures" / "ensemble_model_catalog_snapshot.json"


def test_fixture_declares_all_14_active_pairs_and_8_tolerated_legacy_pairs():
    """f1-d06 (v4): el fixture COMMITTED tiene de verdad los conteos que
    declara, medidos contra el agents.json real."""
    import json

    catalog = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    entries_list = [(e["backend"], e["model"]) for e in catalog["entries"]]
    entries = set(entries_list)
    assert len(entries_list) == len(entries), (
        "el fixture tiene pares (backend, model) DUPLICADOS en entries "
        f"(codex H-04): {len(entries_list)} filas, {len(entries)} unicas"
    )
    config = cepc.load_motor_config()
    profiles = config["ensemble_profiles"]
    active_pairs = {
        (p["backend"], p["model"])
        for p in profiles.values()
        if p.get("backend") in ("opencode", "kilo") and p.get("status") != "legacy"
    }
    legacy_pairs = {
        (p["backend"], p["model"])
        for p in profiles.values()
        if p.get("backend") in ("opencode", "kilo") and p.get("status") == "legacy"
    }
    assert len(active_pairs) == 14, sorted(active_pairs)
    assert len(legacy_pairs) == 8, sorted(legacy_pairs)
    assert active_pairs <= entries, sorted(active_pairs - entries)
    # codex H-04: los 8 legacy COMPLETOS (7 kilo + 1 opencode historico), no
    # solo el subconjunto kilo -- quitar el legacy opencode del fixture debe
    # tumbar este assert, no solo el de los 7 kilo.
    assert legacy_pairs <= entries, sorted(legacy_pairs - entries)
    kilo_legacy = {pair for pair in legacy_pairs if pair[0] == "kilo"}
    assert len(kilo_legacy) == 7
    assert kilo_legacy <= entries


def test_check_catalog_real_fixture_passes_against_real_agents_json():
    """f1-d07 (v4): el CONTROL POSITIVO real contra el agents.json REAL."""
    errors = cepc.check_catalog(None, _FIXTURE)
    assert errors == []


def test_cli_module_invocation_without_config_passes_rc0(tmp_path):
    """f1-d07 (v4): comando LITERAL reejecutable, SIEMPRE como modulo (-m)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.check_ensemble_profile_catalog",
            "--catalog",
            str(_FIXTURE),
        ],
        cwd=str(_MOTOR_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_cli_absent_snapshot_returns_rc2_without_traceback(tmp_path):
    missing = tmp_path / "no_existe.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.check_ensemble_profile_catalog",
            "--catalog",
            str(missing),
        ],
        cwd=str(_MOTOR_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr


def _complete_source(**overrides):
    """Fuente con los 5 campos obligatorios (codex H-03); overrides la muta."""
    source = {
        "command": "opencode models",
        "backend": "opencode",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sha256": "a" * 64,
        "generator_version": "1",
    }
    source.update(overrides)
    return source


def _write_catalog(tmp_path, **overrides):
    now = datetime.now(timezone.utc)
    base = {
        "captured_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1000)).isoformat(),
        "sources": [_complete_source()],
        "entries": [{"backend": "opencode", "model": "nan/glm5.3-flash"}],
    }
    base.update(overrides)
    import json

    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "overrides,expect_message",
    [
        ({"sources": []}, "sources"),
        ({"captured_at": "not-a-date"}, "captured_at"),
        ({"entries": "not-a-list"}, "entries"),
    ],
)
def test_check_catalog_three_metadata_fail_closed_conditions(
    tmp_path, overrides, expect_message
):
    path = _write_catalog(tmp_path, **overrides)
    with pytest.raises(cepc.CatalogSnapshotError, match=expect_message):
        cepc.check_catalog(None, path)


@pytest.mark.parametrize(
    "missing_field",
    ["command", "backend", "captured_at", "sha256", "generator_version"],
)
def test_check_catalog_source_missing_any_of_5_mandatory_fields_fails_closed(
    tmp_path, missing_field
):
    """codex H-03: los 5 campos por fuente son OBLIGATORIOS, no opcionales.

    Antes de este fix, _validate_snapshot solo exigia command y backend;
    una fuente sin captured_at/sha256/generator_version pasaba igual. Este
    test parametriza las 5 claves UNA A UNA: quitar cualquiera debe fallar
    cerrado con rc equivalente (CatalogSnapshotError), nunca pasar en silencio.
    """
    incomplete_source = _complete_source()
    del incomplete_source[missing_field]
    path = _write_catalog(tmp_path, sources=[incomplete_source])
    with pytest.raises(cepc.CatalogSnapshotError, match="source missing"):
        cepc.check_catalog(None, path)


def test_cli_source_missing_mandatory_field_returns_rc2_without_traceback(tmp_path):
    """codex H-03 (nivel CLI): una fuente sin `sha256` hace que el comando
    canonico (-m) devuelva rc 2 con mensaje controlado, nunca rc 0 ni
    traceback."""
    incomplete = _complete_source()
    del incomplete["sha256"]
    path = _write_catalog(tmp_path, sources=[incomplete])
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.check_ensemble_profile_catalog",
            "--catalog",
            str(path),
        ],
        cwd=str(_MOTOR_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert "sha256" in proc.stdout + proc.stderr


def test_check_catalog_expired_snapshot_fails_closed(tmp_path):
    """Fecha calculada EN TIEMPO DE EJECUCION (ds H-12): ayer siempre es ayer."""
    now = datetime.now(timezone.utc)
    path = _write_catalog(
        tmp_path,
        captured_at=(now - timedelta(days=2)).isoformat(),
        expires_at=(now - timedelta(days=1)).isoformat(),
    )
    with pytest.raises(cepc.CatalogSnapshotError, match="expired"):
        cepc.check_catalog(None, path)


def test_check_catalog_absent_file_raises_catalog_snapshot_error(tmp_path):
    with pytest.raises(cepc.CatalogSnapshotError):
        cepc.check_catalog(None, tmp_path / "ausente.json")


def test_check_catalog_legacy_served_pair_tolerated_unknown_pair_is_orphan(tmp_path):
    """f1-d06 (v4): un par servido que coincide con un perfil LEGACY existente
    es TOLERADO; un par servido SIN NINGUN perfil es huerfano; un perfil
    ACTIVO sin catalogo sigue bloqueando. Config sintetica pequena para
    aislar exactamente estas 3 ramas."""
    config = {
        "ensemble_profiles": {
            "p_legacy_kilo": {
                "backend": "kilo",
                "model": "nan/glm5.3-flash",
                "status": "legacy",
            },
            "p_active_opencode": {
                "backend": "opencode",
                "model": "nan/glm5.3-flash",
                "status": "active",
            },
            "p_active_without_catalog": {
                "backend": "opencode",
                "model": "nan/no-existe-en-catalogo",
                "status": "active",
            },
        }
    }
    path = _write_catalog(
        tmp_path,
        entries=[
            {"backend": "kilo", "model": "nan/glm5.3-flash"},
            {"backend": "opencode", "model": "nan/glm5.3-flash"},
            {"backend": "opencode", "model": "nan/huerfano-sin-perfil"},
        ],
    )
    import json

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    errors = cepc.check_catalog(config_path, path)
    assert any("no-existe-en-catalogo" in e for e in errors)
    assert any("huerfano-sin-perfil" in e for e in errors)
    assert not any("glm5.3-flash" in e for e in errors if "kilo" in e)
    assert len(errors) == 2


def test_checker_reads_motor_config_not_agent_project_root(tmp_path, monkeypatch):
    """f1-d13 (v4, sonnet H-04): el RESULTADO de check_catalog (no solo
    load_motor_config aislado) es IDENTICO con AGENT_PROJECT_ROOT apuntando a
    un destino ajeno."""
    foreign = tmp_path / "destino_ajeno"
    foreign.mkdir()
    before = cepc.check_catalog(None, _FIXTURE)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(foreign))
    after = cepc.check_catalog(None, _FIXTURE)
    assert before == after == []


def test_refresh_snapshot_captures_two_sources_separately_with_metadata(
    tmp_path, monkeypatch
):
    """f1-d12 (v4, ds H-10): dos fuentes con formato que NO se asume
    compartido; cada fuente lleva su propio hash/version/fecha."""
    calls = []
    opencode_stdout = "opencode nan/glm5.3-flash\nopencode nan/glm5.3\n"
    kilo_stdout = "kilo nan/glm5.3-flash\n"

    def fake_run(command, **kwargs):
        calls.append(command)
        stdout = opencode_stdout if command[0] == "opencode" else kilo_stdout
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(remc.subprocess, "run", fake_run)
    output = tmp_path / "snapshot.json"
    catalog = remc.refresh_snapshot(output, ttl_hours=24)

    assert [c[0] for c in calls] == ["opencode", "kilo"]
    assert len(catalog["sources"]) == 2
    opencode_source, kilo_source = catalog["sources"]
    assert opencode_source["backend"] == "opencode"
    assert kilo_source["backend"] == "kilo"
    assert opencode_source["command"] == "opencode models"
    assert kilo_source["command"] == "kilo models"
    assert (
        opencode_source["sha256"]
        == hashlib.sha256(opencode_stdout.encode("utf-8")).hexdigest()
    )
    assert (
        kilo_source["sha256"] == hashlib.sha256(kilo_stdout.encode("utf-8")).hexdigest()
    )
    assert opencode_source["sha256"] != kilo_source["sha256"]
    assert {"captured_at", "generator_version"} <= set(opencode_source)
    assert {"captured_at", "generator_version"} <= set(kilo_source)
    assert len(catalog["entries"]) == 3
    assert output.exists()


def test_refresh_capture_source_uses_independent_parser_per_backend(monkeypatch):
    """codex H-02: opencode y kilo usan funciones de parseo DISTINTAS e
    INDEPENDIENTES, no un unico `line.partition(" ")` compartido.

    Mutante: sustituye SOLO `_parse_kilo_models_line` por un parser CSV --
    formato estructuralmente DIVERGENTE del de opencode (que sigue siendo
    "<backend> <modelo>" por espacio, SIN TOCAR). Si el parseo fuera un
    unico codigo compartido parametrizado por nombre de ejecutable, cambiar
    el formato de kilo o bien no tendria efecto (seguiria usando el mismo
    partition) o rompería tambien opencode; aqui opencode sigue intacto y
    kilo adopta el nuevo formato, probando que son dos puntos de cambio
    independientes.
    """
    opencode_raw = "opencode nan/glm5.3-flash\n"
    kilo_raw_csv = "kilo,nan/glm5.3-flash\n"

    def fake_run(command, **kwargs):
        stdout = opencode_raw if command[0] == "opencode" else kilo_raw_csv
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def fake_kilo_csv_parser(line):
        backend, separator, model = line.partition(",")
        if separator and backend == "kilo" and model.strip():
            return backend, model.strip()
        return None

    monkeypatch.setattr(remc.subprocess, "run", fake_run)
    monkeypatch.setattr(remc, "_parse_kilo_models_line", fake_kilo_csv_parser)

    _, opencode_entries = remc._capture_source("opencode")
    _, kilo_entries = remc._capture_source("kilo")

    assert opencode_entries == [{"backend": "opencode", "model": "nan/glm5.3-flash"}]
    assert kilo_entries == [{"backend": "kilo", "model": "nan/glm5.3-flash"}]
    assert remc._parse_opencode_models_line("kilo,nan/glm5.3-flash") is None, (
        "el parser de opencode NO debe entender el formato CSV de kilo "
        "(serian el mismo codigo si lo entendiera)"
    )


def test_check_catalog_malformed_entry_fails_closed(tmp_path):
    """FICHA s.4 (V1 r1): un snapshot con `entries` mal formados es
    INVALIDO -> CatalogSnapshotError controlado, nunca KeyError/TypeError
    escapado desde la comprension de pares servidos."""
    path = _write_catalog(tmp_path, entries=[{"backend": "opencode"}])
    with pytest.raises(cepc.CatalogSnapshotError, match="entries"):
        cepc.check_catalog(None, path)


def test_cli_malformed_entry_returns_rc2_without_traceback(tmp_path):
    """Mismo caso a nivel CLI: rc 2 con mensaje controlado, sin traceback."""
    path = _write_catalog(tmp_path, entries=[{"model": "sin-backend"}])
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.check_ensemble_profile_catalog",
            "--catalog",
            str(path),
        ],
        cwd=str(_MOTOR_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert "entries" in proc.stdout + proc.stderr
