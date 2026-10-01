"""Tests de `scripts/remap_evidence_shas.py` (WOT-2026-088b).

Todos los tests usan un repo git SINTETICO y TEMPORAL con su PROPIO `.git`
(hermetico: sin `.git` propio el walk-up de git alcanza el repo real de la
maquina y el fixture mediria el arbol equivocado). NINGUN test lee ni escribe
los ficheros de evidencia REALES del destino: el generador de fixture
reproduce sus propiedades MEDIDAS como invariantes (finales de linea mixtos,
SHAs de 40 y 7 caracteres, filas sin `commit_sha`, duplicadas, una linea
no-JSON, UTF-8 crudo y un SHA huerfano) y un test propio cae si el generador
degrada.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remap_evidence_shas as remap  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers de git hermetico
# ---------------------------------------------------------------------------


def _init_repo(root: Path) -> Path:
    """Repo git REAL con `.git` propio y config de identidad."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    return root


def _rev(repo: Path, rev: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", rev],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _tree_of(repo: Path, sha: str) -> str:
    return _rev(repo, f"{sha}^{{tree}}")


def _commit_file(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], check=True)
    return _rev(repo, "HEAD")


def _commit_tree(repo: Path, tree: str, message: str, parent: str | None = None) -> str:
    args = ["git", "-C", str(repo), "commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    out = subprocess.run(args, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _same_change_pair(repo: Path) -> tuple[str, str]:
    """(old, new) con el MISMO arbol y patch-id; difiere el mensaje."""
    old = _rev(repo, "HEAD")
    new = _commit_tree(repo, _tree_of(repo, old), "reworded message")
    assert old != new
    return old, new


def _same_tree_different_patch(repo: Path) -> tuple[str, str]:
    """Dos commits con el MISMO arbol y PADRES distintos (patch-id distinto)."""
    seed = _rev(repo, "HEAD")
    _commit_file(repo, "a.txt", "a", "add a")
    parent_a = _rev(repo, "HEAD")
    _commit_file(repo, "t.txt", "t", "target")
    tree_t = _tree_of(repo, _rev(repo, "HEAD"))
    c1 = _commit_tree(repo, tree_t, "same change", parent=parent_a)
    c2 = _commit_tree(repo, tree_t, "same change", parent=seed)
    assert _tree_of(repo, c1) == _tree_of(repo, c2)
    return c1, c2


def _ambiguous_prefix(repo: Path) -> str:
    """Prefijo de 4 hex que resuelve a MAS DE UN objeto en `repo`."""
    blob_dir = repo.parent / "ambig-blobs"
    blob_dir.mkdir(exist_ok=True)
    for attempt in range(20):
        files = []
        for i in range(400):
            path = blob_dir / f"b{attempt}_{i}.txt"
            path.write_bytes(f"{attempt}-{i}-{os.getpid()}".encode())
            files.append(str(path))
        out = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin-paths"],
            input="\n".join(files) + "\n",
            capture_output=True,
            text=True,
            check=True,
        )
        by_prefix: dict[str, list[str]] = {}
        for sha in out.stdout.split():
            by_prefix.setdefault(sha[:4], []).append(sha)
        for prefix, shas in by_prefix.items():
            if len(shas) < 2:
                continue
            probe = subprocess.run(
                ["git", "-C", str(repo), "cat-file", "--batch-check"],
                input=f"{prefix}\n",
                capture_output=True,
                text=True,
            )
            if "ambiguous" in probe.stdout:
                return prefix
    raise AssertionError("no se encontro un prefijo ambiguo de 4 caracteres")


# ---------------------------------------------------------------------------
# Helpers de evidencia
# ---------------------------------------------------------------------------


def _evidence_dir(dest: Path) -> Path:
    return dest / ".agent" / "runtime" / "ensemble"


def _row_bytes(row: dict, eol: bytes = b"\n") -> bytes:
    return json.dumps(row, ensure_ascii=False).encode("utf-8") + eol


def _write_evidence(dest: Path, scorecard: bytes, nonces: bytes) -> tuple[Path, Path]:
    ev = _evidence_dir(dest)
    ev.mkdir(parents=True, exist_ok=True)
    sc_path = ev / "scorecard.jsonl"
    non_path = ev / "emitted_nonces.jsonl"
    sc_path.write_bytes(scorecard)
    non_path.write_bytes(nonces)
    return sc_path, non_path


def _pair_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    """Repo con un par valido (mismo arbol y patch-id) y evidencia que lo cita."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "seed.txt", "seed", "seed")
    old, new = _same_change_pair(repo)
    _write_evidence(
        repo,
        _row_bytes({"event": "ronda", "commit_sha": old, "backend_key": "BA10"}),
        _row_bytes({"commit_sha": old, "challenge_nonce": "N1"}),
    )
    return repo, old, new


def _realistic_fixture(tmp_path: Path) -> dict:
    """Generador del fixture realista (D10): propiedades medidas, no mock."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "seed.txt", "semilla", "seed")
    old_full, new_full = _same_change_pair(repo)
    old7 = old_full[:7]
    orphan = "0badc0de" * 5
    non_ascii = "refutaci\u00f3n con acci\u00f3n y se\u00f1al"
    duplicate = {
        "event": "ronda",
        "commit_sha": old7,
        "backend_key": "BA10",
        "evidencia": non_ascii,
    }
    scorecard = (
        _row_bytes(duplicate, b"\r\n")
        + _row_bytes(
            {"event": "ronda", "commit_sha": old7, "backend_key": "BA11"},
            b"\n",
        )
        + _row_bytes(
            {"event": "ronda", "commit_sha": old_full, "backend_key": "BA12"},
            b"\n",
        )
        + _row_bytes({"event": "ronda", "backend_key": "BA13"}, b"\n")
        + _row_bytes(duplicate, b"\r\n")
        + _row_bytes(
            {"event": "ronda", "commit_sha": orphan, "backend_key": "BA14"},
            b"\n",
        )
        + f"linea no json tocada {orphan} fin\n".encode()
    )
    nonces = _row_bytes(
        {"commit_sha": old_full, "challenge_nonce": "N1"}, b"\n"
    ) + _row_bytes({"commit_sha": old7, "challenge_nonce": "N2"}, b"\r\n")
    sc_path, non_path = _write_evidence(repo, scorecard, nonces)
    return {
        "repo": repo,
        "sc_path": sc_path,
        "non_path": non_path,
        "old_full": old_full,
        "new_full": new_full,
        "old7": old7,
        "orphan": orphan,
    }


# ---------------------------------------------------------------------------
# Validacion de argumentos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "maps",
    [
        ["--map", "abc"],
        ["--map", "abc=abc"],
        ["--map", "a=b", "--map", "a=c"],
    ],
)
def test_argumentos_invalidos_salen_2(tmp_path, capsys, maps):
    repo = _init_repo(tmp_path / "repo")
    rc = remap.main(["--project-root", str(repo), "--git-root", str(repo), *maps])
    assert rc == 2
    assert "ERROR" in capsys.readouterr().err


def test_sin_filas_se_decide_antes_de_consultar_git(tmp_path, capsys):
    """Un OLD sin filas es no-op aunque su objeto ya no exista: no se valida."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "seed.txt", "seed", "seed")
    _old, new = _same_change_pair(repo)
    _write_evidence(
        repo,
        _row_bytes({"event": "ronda", "commit_sha": new, "backend_key": "BA10"}),
        _row_bytes({"commit_sha": new, "challenge_nonce": "N1"}),
    )
    ghost = "f" * 40
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{ghost}={new}",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "sin_filas" in out
    assert "objeto_inexistente" not in out


# ---------------------------------------------------------------------------
# Validacion contra git (D2)
# ---------------------------------------------------------------------------


def test_abreviado_ambiguo_se_rechaza_como_ambiguo(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "seed.txt", "seed", "seed")
    prefix = _ambiguous_prefix(repo)
    new = _rev(repo, "HEAD")
    _write_evidence(
        repo,
        _row_bytes({"event": "ronda", "commit_sha": prefix, "backend_key": "BA10"}),
        _row_bytes({"commit_sha": prefix, "challenge_nonce": "N1"}),
    )
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{prefix}={new}",
        ]
    )
    assert rc == 1
    assert "rechazado:ambiguo" in capsys.readouterr().out


def test_patch_id_con_rc_distinto_de_cero_es_error_git(tmp_path, capsys, monkeypatch):
    repo, old, new = _pair_fixture(tmp_path)
    real = remap._git_run

    def fake(git_root, args, input_bytes=None):
        if args and args[0] == "patch-id":
            return subprocess.CompletedProcess(args, 1, b"", b"boom")
        return real(git_root, args, input_bytes)

    monkeypatch.setattr(remap, "_git_run", fake)
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
        ]
    )
    assert rc == 1
    assert "rechazado:error_git" in capsys.readouterr().out


def test_par_con_arbol_distinto_se_rechaza_y_el_fichero_queda_identico(
    tmp_path, capsys
):
    repo, old, _new = _pair_fixture(tmp_path)
    other = _commit_file(repo, "other.txt", "other", "other")
    sc_path, non_path = (
        _evidence_dir(repo) / "scorecard.jsonl",
        (_evidence_dir(repo) / "emitted_nonces.jsonl"),
    )
    before = (sc_path.read_bytes(), non_path.read_bytes())
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={other}",
        ]
    )
    assert rc == 1
    assert "rechazado:arbol_distinto" in capsys.readouterr().out
    assert (sc_path.read_bytes(), non_path.read_bytes()) == before
    assert not (_evidence_dir(repo) / "remap").exists()


def test_par_con_mismo_arbol_y_distinto_patch_id_se_rechaza(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "seed.txt", "s", "seed")
    c1, c2 = _same_tree_different_patch(repo)
    _write_evidence(
        repo,
        _row_bytes({"event": "ronda", "commit_sha": c1, "backend_key": "BA10"}),
        _row_bytes({"commit_sha": c1, "challenge_nonce": "N1"}),
    )
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{c1}={c2}",
        ]
    )
    assert rc == 1
    assert "rechazado:patch_id_distinto" in capsys.readouterr().out


def test_patch_id_vacio_se_rechaza(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    base = _commit_file(repo, "seed.txt", "seed", "seed")
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-qm", "empty"],
        check=True,
    )
    empty = _rev(repo, "HEAD")
    assert _tree_of(repo, empty) == _tree_of(repo, base)
    _write_evidence(
        repo,
        _row_bytes({"event": "ronda", "commit_sha": empty, "backend_key": "BA10"}),
        _row_bytes({"commit_sha": empty, "challenge_nonce": "N1"}),
    )
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{empty}={base}",
        ]
    )
    assert rc == 1
    assert "rechazado:patch_id_vacio" in capsys.readouterr().out


def test_objeto_inexistente_se_rechaza(tmp_path, capsys):
    repo, old, _new = _pair_fixture(tmp_path)
    ghost = "deadbeef" * 5
    _write_evidence(
        repo,
        _row_bytes({"event": "ronda", "commit_sha": ghost, "backend_key": "BA10"}),
        _row_bytes({"commit_sha": ghost, "challenge_nonce": "N1"}),
    )
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{ghost}={old}",
        ]
    )
    assert rc == 1
    assert "rechazado:objeto_inexistente" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Dry-run, exit 1 y --skip-rejected (D1/D3)
# ---------------------------------------------------------------------------


def test_dry_run_por_defecto_no_escribe_nada(tmp_path, capsys):
    repo, old, new = _pair_fixture(tmp_path)
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    before = {
        sc_path: (sc_path.read_bytes(), sc_path.stat().st_mtime_ns),
        non_path: (non_path.read_bytes(), non_path.stat().st_mtime_ns),
    }
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
        ]
    )
    assert rc == 0
    for path, (data, mtime_ns) in before.items():
        assert path.read_bytes() == data
        assert path.stat().st_mtime_ns == mtime_ns
    assert not (_evidence_dir(repo) / "remap").exists()
    assert "metadatos_distintos" in capsys.readouterr().out


def test_dry_run_y_exit_1_no_crean_el_directorio_remap(tmp_path):
    repo, old, new = _pair_fixture(tmp_path)
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
        ]
    )
    assert rc == 0
    assert not (_evidence_dir(repo) / "remap").exists()

    other = _commit_file(repo, "other.txt", "other", "other")
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={other}",
            "--apply",
        ]
    )
    assert rc == 1
    assert not (_evidence_dir(repo) / "remap").exists()


def test_apply_con_rechazado_sin_skip_sale_1_y_no_escribe(tmp_path):
    repo, old, new = _pair_fixture(tmp_path)
    other = _commit_file(repo, "other.txt", "other", "other")
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    with open(sc_path, "ab") as handle:
        handle.write(
            _row_bytes({"event": "ronda", "commit_sha": other, "backend_key": "BA11"})
        )
    with open(non_path, "ab") as handle:
        handle.write(_row_bytes({"commit_sha": other, "challenge_nonce": "N2"}))
    before = (sc_path.read_bytes(), non_path.read_bytes())
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--map",
            f"{other}={old}",
            "--apply",
        ]
    )
    assert rc == 1
    assert (sc_path.read_bytes(), non_path.read_bytes()) == before
    assert not (_evidence_dir(repo) / "remap").exists()


def test_skip_rejected_imprime_no_remapeado_y_sale_0(tmp_path, capsys):
    repo, old, new = _pair_fixture(tmp_path)
    other = _commit_file(repo, "other.txt", "other", "other")
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    with open(sc_path, "ab") as handle:
        handle.write(
            _row_bytes({"event": "ronda", "commit_sha": other, "backend_key": "BA11"})
        )
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--map",
            f"{other}={old}",
            "--apply",
            "--skip-rejected",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert any(line.startswith("NO REMAPEADO") for line in out.splitlines()), out
    lines = sc_path.read_bytes().split(b"\n")
    assert lines[0].decode("utf-8").find(new) != -1
    assert lines[1].decode("utf-8").find(other) != -1


def test_skip_rejected_nunca_remapea_un_rechazado(tmp_path):
    repo, old, new = _pair_fixture(tmp_path)
    other = _commit_file(repo, "other.txt", "other", "other")
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    with open(sc_path, "ab") as handle:
        handle.write(
            _row_bytes({"event": "ronda", "commit_sha": other, "backend_key": "BA11"})
        )
    rejected_row_before = sc_path.read_bytes().split(b"\n")[1]
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--map",
            f"{other}={old}",
            "--apply",
            "--skip-rejected",
        ]
    )
    assert rc == 0
    assert sc_path.read_bytes().split(b"\n")[1] == rejected_row_before


# ---------------------------------------------------------------------------
# Localizacion del valor y preservacion de bytes (D4/D10)
# ---------------------------------------------------------------------------


def test_fila_ambigua_y_linea_no_json_con_old_no_se_tocan_y_se_listan(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "seed.txt", "seed", "seed")
    old, new = _same_change_pair(repo)
    ambiguous = _row_bytes(
        {
            "commit_sha": old,
            "nested": {"commit_sha": old},
        }
    )
    non_json = f"garbage {old} tail\n".encode()
    valid = _row_bytes({"event": "ronda", "commit_sha": old, "backend_key": "BA10"})
    sc_path, _non_path = _write_evidence(repo, ambiguous + non_json + valid, b"")
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--apply",
        ]
    )
    assert rc == 0
    lines = sc_path.read_bytes().split(b"\n")
    assert lines[0] == ambiguous.rstrip(b"\n")
    assert lines[1] == non_json.rstrip(b"\n")
    assert old.encode() not in lines[2]
    out = capsys.readouterr().out
    assert "fila_ambigua" in out
    assert "linea_no_json_con_old" in out


def test_sustitucion_preserva_bytes_finales_mixtos_y_utf8_crudo(tmp_path):
    fixture = _realistic_fixture(tmp_path)
    repo = fixture["repo"]
    sc_path = fixture["sc_path"]
    old7 = fixture["old7"]
    new_full = fixture["new_full"]
    before = sc_path.read_bytes()
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old7}={new_full}",
            "--apply",
        ]
    )
    assert rc == 0
    after = sc_path.read_bytes()
    before_lines = before.split(b"\n")
    after_lines = after.split(b"\n")
    assert len(before_lines) == len(after_lines)
    changed = 0
    for b_line, a_line in zip(before_lines, after_lines, strict=False):
        if b_line == a_line:
            continue
        changed += 1
        assert a_line == b_line.replace(old7.encode(), new_full.encode())
        assert a_line.endswith(b"\r") == b_line.endswith(b"\r")
    assert changed == 3
    assert "\u00f3".encode() in after
    assert b"linea no json tocada" in after


def test_abreviado_solo_remapea_valor_exacto(tmp_path):
    fixture = _realistic_fixture(tmp_path)
    repo = fixture["repo"]
    sc_path = fixture["sc_path"]
    old_full = fixture["old_full"]
    old7 = fixture["old7"]
    new_full = fixture["new_full"]
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old7}={new_full}",
            "--apply",
        ]
    )
    assert rc == 0
    lines = sc_path.read_bytes().split(b"\n")
    assert old7.encode() not in lines[0]
    assert new_full.encode() in lines[0]
    assert old_full.encode() in lines[2]


def test_fixture_reproduce_las_propiedades_medidas(tmp_path):
    """Si el generador degrada (pierde una propiedad medida), este test cae."""
    fixture = _realistic_fixture(tmp_path)
    repo = fixture["repo"]
    sc_raw = fixture["sc_path"].read_bytes()
    non_raw = fixture["non_path"].read_bytes()

    for raw in (sc_raw, non_raw):
        crlf = raw.count(b"\r\n")
        bare_lf = raw.count(b"\n") - crlf
        assert crlf > 0, "el fixture debe tener al menos un CRLF"
        assert bare_lf > 0, "el fixture debe tener al menos un LF solitario"

    sc_text = sc_raw.decode("utf-8")
    assert fixture["old_full"] in sc_text
    assert fixture["old7"] in sc_text
    assert len(fixture["old_full"]) == 40
    assert len(fixture["old7"]) == 7
    assert '"backend_key": "BA13"' in sc_text
    rows = [line for line in sc_text.splitlines() if line.strip()]
    assert len(rows) != len(set(rows)), "debe haber una fila duplicada"
    assert any(_parse_fails(line) for line in rows), "debe haber una linea no-JSON"
    assert any(byte > 127 for byte in sc_raw), "debe haber UTF-8 crudo"
    assert fixture["orphan"] in sc_text
    probe = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{fixture['orphan']}^{{commit}}"],
        capture_output=True,
    )
    assert probe.returncode != 0, "el SHA huerfano no debe existir en el fixture"


def _parse_fails(line: str) -> bool:
    try:
        json.loads(line)
    except json.JSONDecodeError:
        return True
    return False


# ---------------------------------------------------------------------------
# Atomicidad, idempotencia y artefactos (D7/D8)
# ---------------------------------------------------------------------------


def test_cambio_concurrente_antes_del_replace_aborta_y_restaura(
    tmp_path, capsys, monkeypatch
):
    repo, old, new = _pair_fixture(tmp_path)
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    before = (sc_path.read_bytes(), non_path.read_bytes())
    calls = {"n": 0}
    real = remap._verify_unchanged

    def flaky(path, expected):
        calls["n"] += 1
        if calls["n"] == 2:
            raise remap._ConcurrentWriteError("simulado: otro proceso escribio")
        return real(path, expected)

    monkeypatch.setattr(remap, "_verify_unchanged", flaky)
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--apply",
        ]
    )
    assert rc == 2
    assert (sc_path.read_bytes(), non_path.read_bytes()) == before
    assert "ABORTADO" in capsys.readouterr().err
    assert not list((_evidence_dir(repo) / "remap").glob("*.inprogress.json"))
    assert _remap_copies(repo) == []


def test_fallo_inyectado_en_el_segundo_fichero_restaura_el_primero(
    tmp_path, capsys, monkeypatch
):
    repo, old, new = _pair_fixture(tmp_path)
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    before = (sc_path.read_bytes(), non_path.read_bytes())
    calls = {"n": 0}
    real = remap._replace_file

    def flaky(path, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disco simulado")
        return real(path, data)

    monkeypatch.setattr(remap, "_replace_file", flaky)
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--apply",
        ]
    )
    assert rc == 2
    assert (sc_path.read_bytes(), non_path.read_bytes()) == before
    assert "ABORTADO" in capsys.readouterr().err
    assert _remap_copies(repo) == []


def test_inprogress_residual_hace_salir_2_sin_restaurar(tmp_path, capsys):
    repo, old, new = _pair_fixture(tmp_path)
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    before = (sc_path.read_bytes(), non_path.read_bytes())
    remap_dir = _evidence_dir(repo) / "remap"
    remap_dir.mkdir(parents=True)
    sentinel = remap_dir / "remap_20200101T000000000000Z.inprogress.json"
    sentinel.write_text(
        json.dumps(
            {
                "timestamp": "20200101T000000000000Z",
                "ficheros": [{"fichero": str(sc_path), "copia": str(sc_path) + ".bak"}],
            }
        ),
        encoding="utf-8",
    )
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--apply",
        ]
    )
    assert rc == 2
    assert (sc_path.read_bytes(), non_path.read_bytes()) == before
    assert sentinel.exists()
    assert "RESTAURACION MANUAL" in capsys.readouterr().err


def test_una_copia_pre_remap_nunca_se_sobrescribe(tmp_path, capsys, monkeypatch):
    repo, old, new = _pair_fixture(tmp_path)
    monkeypatch.setattr(remap, "_utc_stamp", lambda: "20200101T000000000000Z")
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    before = sc_path.read_bytes()
    remap_dir = _evidence_dir(repo) / "remap"
    remap_dir.mkdir(parents=True)
    existing = remap_dir / "scorecard.jsonl.pre-remap.20200101T000000000000Z"
    existing.write_bytes(b"previa")
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--apply",
        ]
    )
    assert rc == 2
    assert sc_path.read_bytes() == before
    assert existing.read_bytes() == b"previa"
    assert "NUNCA se sobrescribe" in capsys.readouterr().err


def test_segunda_ejecucion_no_cambia_datos_ni_crea_artefactos(tmp_path):
    repo, old, new = _pair_fixture(tmp_path)
    args = [
        "--project-root",
        str(repo),
        "--git-root",
        str(repo),
        "--map",
        f"{old}={new}",
        "--apply",
    ]
    assert remap.main(args) == 0
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    after_first = (sc_path.read_bytes(), non_path.read_bytes())
    artifacts = sorted(p.name for p in (_evidence_dir(repo) / "remap").iterdir())
    assert remap.main(args) == 0
    assert (sc_path.read_bytes(), non_path.read_bytes()) == after_first
    assert (
        sorted(p.name for p in (_evidence_dir(repo) / "remap").iterdir()) == artifacts
    )


# ---------------------------------------------------------------------------
# Denominador, huerfanos y referencias externas (D5/D6)
# ---------------------------------------------------------------------------


def test_denominador_cero_sale_2(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _sc_path, non_path = _write_evidence(repo, b"", b"")
    rc = remap.main(["--project-root", str(repo), "--git-root", str(repo)])
    assert rc == 2
    assert "denominador cero" in capsys.readouterr().err

    non_path.unlink()
    rc = remap.main(["--project-root", str(repo), "--git-root", str(repo)])
    assert rc == 2
    assert "falta el fichero de evidencia" in capsys.readouterr().err


def test_huerfanos_se_informan_sin_map(tmp_path, capsys):
    fixture = _realistic_fixture(tmp_path)
    rc = remap.main(
        ["--project-root", str(fixture["repo"]), "--git-root", str(fixture["repo"])]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "huerfanos" in out
    assert fixture["orphan"] in out


def test_referencias_fuera_de_los_dos_jsonl_se_listan_y_no_se_reescriben(
    tmp_path, capsys
):
    repo, old, new = _pair_fixture(tmp_path)
    inventory = _evidence_dir(repo) / "backend_status.json"
    inventory.write_bytes(
        json.dumps({"nota": f"cita {old} y nada mas"}).encode("utf-8")
    )
    before = inventory.read_bytes()
    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--apply",
        ]
    )
    assert rc == 0
    assert inventory.read_bytes() == before
    out = capsys.readouterr().out
    assert "backend_status.json" in out
    report_path = next((_evidence_dir(repo) / "remap").glob("remap_*.json"))
    report = json.loads(report_path.read_bytes().decode("utf-8"))
    assert any(
        ref["fichero"] == "backend_status.json" and ref["ocurrencias"] >= 1
        for ref in report["referencias_externas"]
    )


# ---------------------------------------------------------------------------
# CHANGES del MANAGER_REVIEW (DBL-5, ancla d3dc5e9): limpieza y captura en los
# caminos de error de _apply_changes, y cabecera del objeto commit
# ---------------------------------------------------------------------------

_STAMP = "20200101T000000000000Z"


def _apply_args(repo: Path, old: str, new: str) -> list[str]:
    return [
        "--project-root",
        str(repo),
        "--git-root",
        str(repo),
        "--map",
        f"{old}={new}",
        "--apply",
    ]


def _remap_copies(repo: Path) -> list[str]:
    remap_dir = _evidence_dir(repo) / "remap"
    if not remap_dir.is_dir():
        return []
    return sorted(p.name for p in remap_dir.glob("*.pre-remap.*"))


def test_fallo_al_escribir_el_sentinela_limpia_copias_y_sale_2(
    tmp_path, capsys, monkeypatch
):
    """Blocker 1: un OSError al escribir el sentinela NO escapa; limpia copias."""
    repo, old, new = _pair_fixture(tmp_path)
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    before = (sc_path.read_bytes(), non_path.read_bytes())
    real = remap._write_bytes

    def flaky(path, data):
        if path.name.endswith(".inprogress.json"):
            raise OSError("sentinela simulado")
        return real(path, data)

    monkeypatch.setattr(remap, "_write_bytes", flaky)
    rc = remap.main(_apply_args(repo, old, new))
    assert rc == 2
    assert (sc_path.read_bytes(), non_path.read_bytes()) == before
    assert _remap_copies(repo) == []
    assert not list((_evidence_dir(repo) / "remap").glob("*.inprogress.json"))
    assert "sentinela" in capsys.readouterr().err


def test_fallo_en_la_copia_enesima_limpia_las_anteriores(tmp_path, capsys, monkeypatch):
    """Blocker 3: si la copia N falla, las copias 1..N-1 de ESTA ejecucion se borran."""
    repo, old, new = _pair_fixture(tmp_path)
    monkeypatch.setattr(remap, "_utc_stamp", lambda: _STAMP)
    sc_path = _evidence_dir(repo) / "scorecard.jsonl"
    non_path = _evidence_dir(repo) / "emitted_nonces.jsonl"
    before = (sc_path.read_bytes(), non_path.read_bytes())
    remap_dir = _evidence_dir(repo) / "remap"
    remap_dir.mkdir(parents=True)
    preexisting = remap_dir / f"emitted_nonces.jsonl.pre-remap.{_STAMP}"
    preexisting.write_bytes(b"previa")
    rc = remap.main(_apply_args(repo, old, new))
    assert rc == 2
    assert (sc_path.read_bytes(), non_path.read_bytes()) == before
    assert not (remap_dir / f"scorecard.jsonl.pre-remap.{_STAMP}").exists()
    assert preexisting.read_bytes() == b"previa"
    assert "NUNCA se sobrescribe" in capsys.readouterr().err


def test_fallo_de_restore_en_rollback_sale_2_y_conserva_su_copia(
    tmp_path, capsys, monkeypatch
):
    """Blocker 4: un fallo dentro del propio rollback no propaga; exit 2, sentinela
    borrado y la copia del fichero no restaurado se CONSERVA como red manual."""
    repo, old, new = _pair_fixture(tmp_path)
    monkeypatch.setattr(remap, "_utc_stamp", lambda: _STAMP)
    calls = {"n": 0}
    real = remap._replace_file

    def flaky(path, data):
        calls["n"] += 1
        if calls["n"] in (2, 3):
            raise OSError("fallo simulado")
        return real(path, data)

    monkeypatch.setattr(remap, "_replace_file", flaky)
    rc = remap.main(_apply_args(repo, old, new))
    assert rc == 2
    err = capsys.readouterr().err
    assert "no pude restaurar" in err
    remap_dir = _evidence_dir(repo) / "remap"
    assert (remap_dir / f"scorecard.jsonl.pre-remap.{_STAMP}").exists()
    assert not (remap_dir / f"emitted_nonces.jsonl.pre-remap.{_STAMP}").exists()
    assert not list(remap_dir.glob("*.inprogress.json"))


def test_metadata_differs_no_descarta_lineas_del_mensaje_que_empiezan_por_tree(
    tmp_path,
):
    """Hallazgo 5: solo la CABECERA `tree <sha>` se descarta; una linea del
    mensaje que empiece por `tree ` es contenido y cuenta como diferencia."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "seed.txt", "seed", "seed")
    tree = _tree_of(repo, _rev(repo, "HEAD"))
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
    }

    def _commit_msg(message: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(repo), "commit-tree", tree, "-m", message],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return out.stdout.strip()

    old = _commit_msg("tree alpha\n\ncuerpo")
    new = _commit_msg("tree beta\n\ncuerpo")
    assert old != new
    assert _tree_of(repo, old) == _tree_of(repo, new)
    assert remap._metadata_differs(repo, old, new) is True
