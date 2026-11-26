"""Contract tests for the read-only L-6 archive checker.

Before: the tests receive only synthetic JSONL indexes and archive trees.
During: exercise both the CLI-facing and heartbeat-facing interfaces, including
    declared mutation probes.
After: every minimum L-6 invariant is covered without touching a real archive.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
L6_PATH = ROOT / "scripts" / "flight" / "check_l6.py"
STALL_PATH = ROOT / "scripts" / "flight" / "flight_stall_check.py"


def _load(path: Path, name: str):
    """Load one source file by path, matching the production loader contract."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


l6 = _load(L6_PATH, "test_check_l6")
stall = _load(STALL_PATH, "test_stall_shared")


def _write_index(tmp_path: Path, rows: list[dict], family: str = "fam") -> Path:
    """Create an index and its family root without consulting a real archive."""
    root = tmp_path / "archive"
    (root / family).mkdir(parents=True, exist_ok=True)
    index = root / "index.jsonl"
    index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return index


def _row(name: str, status: str = "ARCHIVADO", family: str = "fam") -> dict:
    """Return the smallest realistic archive-index row for a test."""
    return {
        "status": status,
        "family": family,
        "zip": f"{family}/{name}.zip",
        "manifest": f"{family}/{name}.json",
    }


def _tree_manifest(root: Path) -> dict[str, tuple[int, str]]:
    """Return a stable manifest of the synthetic tree."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = (
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return result


@pytest.fixture(autouse=True)
def wot_l6_mutant(monkeypatch):  # noqa: C901
    """Apply one declared negative-control mutation when requested by the gate."""
    mutant = os.environ.get("WOT_L6_MUTANT")
    if not mutant:
        yield
        return

    original_run = l6.run_check_l6
    original_check = l6.check_l6
    original_path_open = Path.open

    if mutant == "m01_escribe_indice":

        def mutated_run(index):
            result = original_run(index)
            with original_path_open(Path(index), "ab") as handle:
                handle.write(b"x")
            return result

        monkeypatch.setattr(l6, "run_check_l6", mutated_run)
    elif mutant == "m03_reconcile_index_neutralizada":
        monkeypatch.setattr(l6.p7_common, "reconcile_index", lambda *_args: [])
    elif mutant == "m04_rc_fijo_0":
        monkeypatch.setattr(
            l6, "run_check_l6", lambda index: (0, original_run(index)[1])
        )
    elif mutant == "m04_rc_fijo_1":
        monkeypatch.setattr(
            l6, "run_check_l6", lambda index: (1, original_run(index)[1])
        )
    elif mutant == "m05_etiqueta_fichero_sin_fila":
        monkeypatch.setattr(
            l6,
            "run_check_l6",
            lambda index: (
                lambda pair: (
                    pair[0],
                    [
                        (
                            "l6-fichero-sin-fila"
                            if key == "l6-indice-retirado-local"
                            else key,
                            level,
                            text,
                        )
                        for key, level, text in pair[1]
                    ],
                )
            )(original_run(index)),
        )
    elif mutant in {"m05_suprime_fila_sin_fichero", "m05_suprime_fichero_sin_fila"}:
        needle = (
            "l6-fila-sin-fichero"
            if mutant.endswith("fila_sin_fichero")
            else "l6-fichero-sin-fila"
        )
        monkeypatch.setattr(
            l6,
            "run_check_l6",
            lambda index: (
                lambda pair: (pair[0], [item for item in pair[1] if item[0] != needle])
            )(original_run(index)),
        )
    elif mutant == "m06_devuelve_tupla_rc_lista":
        monkeypatch.setattr(
            l6,
            "check_l6",
            lambda out, index: (
                original_check(out, index) and (1, original_check(out, index))
            ),
        )
    elif mutant == "m06_clave_sin_prefijo":
        monkeypatch.setattr(
            l6,
            "check_l6",
            lambda out, index: [
                (key[3:], level, text)
                for key, level, text in original_check(out, index)
            ],
        )
    elif mutant == "m06_nivel_no_aviso":
        monkeypatch.setattr(
            l6,
            "check_l6",
            lambda out, index: [
                (key, "ERROR", text) for key, _level, text in original_check(out, index)
            ],
        )
    elif mutant == "m07_ignora_archive_index":
        monkeypatch.setattr(
            l6, "check_l6", lambda out, _index: original_check(out, None)
        )
    elif mutant == "m06_owned_prefixes_sin_l6":
        monkeypatch.setattr(
            stall,
            "OWNED_PREFIXES",
            tuple(p for p in stall.OWNED_PREFIXES if p != "l6-"),
        )
    elif mutant == "m02_no_archive_index_arg":
        original_main = stall.main

        def no_archive_index(argv=None):
            argv = [
                value
                for value in (argv or [])
                if value != "--archive-index" and value != "SENT"
            ]
            return original_main(argv)

        monkeypatch.setattr(stall, "main", no_archive_index)
    yield


def test_m01_solo_lectura_sin_modo_escritura(tmp_path, monkeypatch):
    """The checker must not open any synthetic artifact for writing."""
    index = _write_index(tmp_path, [_row("ok")])
    (index.parent / "fam" / "ok.zip").write_bytes(b"zip")
    (index.parent / "fam" / "ok.json").write_bytes(b"manifest")
    before = (
        _tree_manifest(index.parent),
        index.stat().st_mtime_ns,
        hashlib.sha256(index.read_bytes()).hexdigest(),
    )
    calls = []

    def audit_open(*args, **kwargs):
        mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
        if any(flag in mode for flag in "wax+"):
            calls.append((args, kwargs))
            raise AssertionError("apertura de escritura")
        return original_open(*args, **kwargs)

    original_open = builtins.open
    monkeypatch.setattr("builtins.open", audit_open)
    monkeypatch.setattr("io.open", audit_open)
    monkeypatch.setattr(
        "os.open",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("os.open")),
    )
    monkeypatch.setattr(
        Path, "open", lambda self, *args, **kwargs: audit_open(self, *args, **kwargs)
    )
    l6.run_check_l6(index)
    l6.check_l6({}, index)
    after = (
        _tree_manifest(index.parent),
        index.stat().st_mtime_ns,
        hashlib.sha256(index.read_bytes()).hexdigest(),
    )
    assert not calls
    assert after == before


def test_m02_archive_index_flag_sets_cfg_and_defaults_none():
    """The optional CLI value is observable as CFG.archive_index."""
    seen = []

    def fake_run(args):
        seen.append(getattr(args, "archive_index", "MISSING"))
        return 0

    stall.run = fake_run
    stall.main([])
    stall.main(["--archive-index", "SENT"])
    assert seen == [None, "SENT"]


def test_m03_reconcile_index_es_necesaria(tmp_path):
    """Neutralizing the shared reconciler changes the observed findings."""
    index = _write_index(tmp_path, [_row("missing")])
    baseline = l6.run_check_l6(index)[1]
    assert any(item[0] == "l6-fila-sin-fichero" for item in baseline)


def test_m04_rc_0_sin_hallazgos(tmp_path):
    index = _write_index(tmp_path, [_row("ok")])
    (index.parent / "fam" / "ok.zip").write_bytes(b"zip")
    (index.parent / "fam" / "ok.json").write_bytes(b"manifest")
    assert l6.run_check_l6(index) == (0, [])


def test_m04_rc_1_con_discrepancia(tmp_path):
    rc, findings = l6.run_check_l6(_write_index(tmp_path, [_row("missing")]))
    assert rc == 1 and findings


def test_m04_run_check_l6_devuelve_3_tuplas(tmp_path):
    findings = l6.run_check_l6(_write_index(tmp_path, [_row("missing")]))[1]
    assert all(isinstance(item, tuple) and len(item) == 3 for item in findings)


def test_m04_archivo_no_montado_es_aviso_no_excepcion(tmp_path):
    rc, findings = l6.run_check_l6(tmp_path / "missing" / "index.jsonl")
    assert rc == 1 and findings == [("l6-archivo-no-montado", "AVISO", findings[0][2])]


def test_m05_retirado_local_es_aviso_nunca_fichero_sin_fila(tmp_path):
    row = _row("retired", "RETIRADO_LOCAL")
    index = _write_index(tmp_path, [row])
    (index.parent / "fam" / "retired.zip").write_bytes(b"zip")
    (index.parent / "fam" / "retired.json").write_bytes(b"manifest")
    _, findings = l6.run_check_l6(index)
    assert sum(item[0] == "l6-indice-retirado-local" for item in findings) == 1
    assert not any(item[0] == "l6-fichero-sin-fila" for item in findings)


def test_m05_reconciliacion_bidireccional_emite_fila_sin_fichero(tmp_path):
    _, findings = l6.run_check_l6(_write_index(tmp_path, [_row("missing")]))
    item = next(item for item in findings if item[0] == "l6-fila-sin-fichero")
    assert item[1] == "AVISO"


def test_m05_reconciliacion_bidireccional_emite_fichero_sin_fila(tmp_path):
    index = _write_index(tmp_path, [])
    (index.parent / "fam" / "orphan.zip").write_bytes(b"zip")
    _, findings = l6.run_check_l6(index)
    item = next(item for item in findings if item[0] == "l6-fichero-sin-fila")
    assert item[1] == "AVISO"


def test_m06_cara_detector_devuelve_solo_3_tuplas(tmp_path):
    found = l6.check_l6({}, _write_index(tmp_path, [_row("missing")]))
    assert isinstance(found, list) and all(
        isinstance(item, tuple) and len(item) == 3 for item in found
    )


def test_m06_retorno_none_activa_detector_roto(monkeypatch):
    monkeypatch.setattr(
        stall,
        "_load_l6",
        lambda: SimpleNamespace(check_l6=lambda _out, _index: None),
    )
    monkeypatch.setattr(stall, "CFG", SimpleNamespace(archive_index="SENT"))
    found, broke = stall._detect({}, {}, "l6")
    assert broke is True and found and found[0][0] == "detector-roto"


def test_m06_claves_con_prefijo_l6(tmp_path):
    assert all(
        item[0].startswith("l6-")
        for item in l6.check_l6({}, _write_index(tmp_path, [_row("missing")]))
    )


def test_m06_niveles_aviso(tmp_path):
    assert all(
        item[1] == "AVISO"
        for item in l6.check_l6({}, _write_index(tmp_path, [_row("missing")]))
    )


def test_m06_owned_prefixes_includes_l6():
    assert "l6-" in stall.OWNED_PREFIXES


def test_m07_archive_index_ausente_detector_inerte(monkeypatch):
    monkeypatch.setattr(stall, "_load_l6", lambda: l6)
    monkeypatch.setattr(stall, "CFG", SimpleNamespace())
    found, broke = stall._detect({}, {}, "l6")
    assert not broke and not found


def test_m07_archive_index_sintetico_emite_aviso(tmp_path, monkeypatch):
    monkeypatch.setattr(stall, "_load_l6", lambda: l6)
    monkeypatch.setattr(
        stall,
        "CFG",
        SimpleNamespace(archive_index=_write_index(tmp_path, [_row("missing")])),
    )
    found, broke = stall._detect({}, {}, "l6")
    assert not broke and any(
        key == "l6-fila-sin-fichero" for key, _level, _text in found
    )
