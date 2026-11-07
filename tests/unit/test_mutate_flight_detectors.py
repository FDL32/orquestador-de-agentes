"""Pruebas del arnés de mutación de los detectores de vuelo."""

import contextlib
import importlib.util
import io
import shutil
import sys
import tempfile
from pathlib import Path


__doc__ = (
    (__doc__ or "")
    + """

Formas de entrada -> test:
objetivo ausente/OSError -> test_validate_rechaza_fichero_ausente_sin_otro_motivo;
bytes UTF-8 inválidos -> test_main_rechaza_objetivo_ilegible_por_unicodeerror_rc_1;
0 coincidencias -> test_validate_rechaza_patron_inexistente_sin_otro_motivo;
2 coincidencias -> test_validate_rechaza_patron_duplicado_sin_otro_motivo;
mutante igual -> test_validate_rechaza_mutacion_igual_sin_otro_motivo;
no compila -> test_validate_rechaza_mutacion_no_compilable_sin_otro_motivo;
id duplicado -> test_validate_rechaza_id_duplicado_sin_otro_motivo;
tabla vacía -> test_tabla_vacia_es_rc_1;
caja o id desconocido -> test_flags_detectores_controlan_rutas_distintas.
"""
)


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "flight" / "mutate_flight_detectors.py"


def _load_harness():
    """Carga el arnés sin ejecutar sus corridas.

    Before: ``HARNESS`` apunta al script versionado del ticket.
    During: importa el módulo mediante su ruta, sin alterar ``sys.path``.
    After: devuelve el módulo cargado o propaga el error de importación.
    """
    spec = importlib.util.spec_from_file_location("mutate_flight_detectors", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(root):
    """Devuelve el árbol completo de ficheros con bytes y rutas relativas."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_catalogo_de_mutaciones_y_reanclajes_es_completo():
    """El arnés conserva el denominador completo y los 12 reanclajes de 153j."""
    module = _load_harness()

    assert len(module.MUT) == 180
    assert module.RETIRED == {}
    assert set(module.REANCHORED) == {
        "E7",
        "N70",
        "N64",
        "Q3c",
        "X16",
        "Q7b",
        "Q7c",
        "T5",
        "T6",
        "Q1",
        "Q2",
        "Q14",
    }
    assert all(module.REANCHORED.values())
    assert module.main(["--repo", str(ROOT), "--validate-only"]) == 0


def test_cada_patron_casa_una_vez_compila_y_cambia_el_objetivo():
    """La validación reproduce las tres barreras del contrato D23."""
    module = _load_harness()
    for _mid, _box, target, pattern, replacement in module.MUT:
        source = (ROOT / "scripts" / "flight" / target).read_text(encoding="utf-8")
        assert source.count(pattern) == 1
        mutated = source.replace(pattern, replacement)
        assert mutated != source
        compile(mutated, target, "exec")


def test_main_rechaza_patron_inexistente_por_rc_1(tmp_path):
    module = _load_harness()
    repo = _synthetic_repo(tmp_path)
    module.MUT = _synthetic("MAIN0", "missing", "x")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_rechaza_objetivo_ilegible_por_unicodeerror_rc_1(capsys, tmp_path):
    module = _load_harness()
    repo = _synthetic_repo(tmp_path)
    (repo / "scripts" / "flight" / "flight_stall_check.py").write_bytes(b"\xff\xfe")
    module.MUT = _synthetic("W1", "x", "y")

    def executor(*_args):
        raise AssertionError("executor")

    assert module.main(["--repo", str(repo), "--validate-only"], executor) == 1
    output = capsys.readouterr().out
    assert "W1" in output and "no se puede leer" in output


def test_formas_de_entrada_documentadas_existen():
    names = (
        "test_validate_rechaza_fichero_ausente_sin_otro_motivo",
        "test_main_rechaza_objetivo_ilegible_por_unicodeerror_rc_1",
        "test_validate_rechaza_patron_inexistente_sin_otro_motivo",
        "test_validate_rechaza_patron_duplicado_sin_otro_motivo",
        "test_validate_rechaza_mutacion_igual_sin_otro_motivo",
        "test_validate_rechaza_mutacion_no_compilable_sin_otro_motivo",
        "test_validate_rechaza_id_duplicado_sin_otro_motivo",
        "test_tabla_vacia_es_rc_1",
        "test_flags_detectores_controlan_rutas_distintas",
    )
    for name in names:
        assert callable(getattr(sys.modules[__name__], name))


def _synthetic_repo(tmp_path, text="abc"):
    """Crea una raíz mínima para probar una sola barrera del arnés."""
    flight = tmp_path / "scripts" / "flight"
    flight.mkdir(parents=True)
    (flight / "flight_stall_check.py").write_text(text, encoding="utf-8")
    (flight / "quota_tick.py").write_text("abc", encoding="utf-8")
    return tmp_path


def _synthetic(mid, pattern, replacement, target="flight_stall_check.py"):
    return [(mid, "synthetic", target, pattern, replacement)]


def _tmp_dirs(prefix):
    """Cuenta directorios temporales vivos del arnés por prefijo."""
    return {
        path for path in Path(tempfile.gettempdir()).glob(prefix + "*") if path.is_dir()
    }


def test_validate_rechaza_patron_inexistente_sin_otro_motivo(tmp_path):
    module = _load_harness()
    errors = module.validate(
        _synthetic_repo(tmp_path), _synthetic("H1", "missing", "x")
    )
    assert len(errors) == 1 and "casa 0" in errors[0]


def test_validate_rechaza_patron_duplicado_sin_otro_motivo(tmp_path):
    module = _load_harness()
    errors = module.validate(
        _synthetic_repo(tmp_path, "abcabc"), _synthetic("H2", "abc", "x")
    )
    assert len(errors) == 1 and "casa 2" in errors[0]


def test_validate_rechaza_mutacion_igual_sin_otro_motivo(tmp_path):
    module = _load_harness()
    errors = module.validate(_synthetic_repo(tmp_path), _synthetic("H3", "abc", "abc"))
    assert errors == ["H3: la mutacion no difiere del original"]


def test_validate_rechaza_mutacion_no_compilable_sin_otro_motivo(tmp_path):
    module = _load_harness()
    errors = module.validate(
        _synthetic_repo(tmp_path, "value = 1"), _synthetic("H4", "value = 1", "if (")
    )
    assert len(errors) == 1 and "no compila" in errors[0]


def test_validate_rechaza_id_duplicado_sin_otro_motivo(tmp_path):
    module = _load_harness()
    mutations = _synthetic("H5", "a", "x") + _synthetic("H5", "b", "y")
    errors = module.validate(_synthetic_repo(tmp_path, "ab"), mutations)
    assert errors == ["H5: id duplicado"]


def test_validate_rechaza_fichero_ausente_sin_otro_motivo(tmp_path):
    module = _load_harness()
    errors = module.validate(
        _synthetic_repo(tmp_path), _synthetic("H6", "abc", "x", "missing.py")
    )
    assert len(errors) == 1 and "no se puede leer" in errors[0]


def test_main_rechaza_patron_duplicado_por_rc_1(tmp_path):
    module = _load_harness()
    repo = _synthetic_repo(tmp_path, "abcabc")
    module.MUT = _synthetic("MAIN2", "abc", "x")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_rechaza_mutacion_igual_por_rc_1(tmp_path):
    module = _load_harness()
    repo = _synthetic_repo(tmp_path)
    module.MUT = _synthetic("MAIN3", "abc", "abc")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_rechaza_mutacion_no_compilable_por_rc_1(tmp_path):
    module = _load_harness()
    repo = _synthetic_repo(tmp_path, "value = 1")
    module.MUT = _synthetic("MAIN4", "value = 1", "if (")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_inject_bad_pattern_nombra_bad_y_rc_1(capsys):
    module = _load_harness()
    assert (
        module.main(["--repo", str(ROOT), "--validate-only", "--inject-bad-pattern"])
        == 1
    )
    assert "BAD" in capsys.readouterr().out


def test_tabla_vacia_es_rc_1(monkeypatch):
    module = _load_harness()
    monkeypatch.setattr(module, "MUT", [])
    assert module.main(["--repo", str(ROOT), "--validate-only"]) == 1


def test_executor_rc_5_y_rc_2_son_errores_no_muertes():
    module = _load_harness()
    for rc in (5, 2):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = module.main(
                ["--repo", str(ROOT), "--ids", "E7"],
                executor=lambda _repo, _env, _tests, rc=rc: (rc, "bad executor"),
            )
        text = output.getvalue()
        assert result == 1
        assert "ERROR E7" in text
        assert "matadas 0/1" in text


def test_timeout_no_es_muerte_y_superviviente_no_adjudicado():
    module = _load_harness()
    for rc, label in ((99, "TIMEOUT"), (0, "SURVIVE")):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = module.main(
                ["--repo", str(ROOT), "--ids", "E7"],
                executor=lambda _repo, _env, _tests, rc=rc: (rc, "synthetic"),
            )
        assert result == 1
        assert f"{label} E7" in output.getvalue()
        assert "matadas 0/1" in output.getvalue()
        if rc == 99:
            assert "errores: ninguno" in output.getvalue()


def test_equiv_se_informa_aparte_y_no_es_superviviente():
    module = _load_harness()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = module.main(
            ["--repo", str(ROOT), "--ids", "N69"],
            executor=lambda _repo, _env, _tests: (0, "equivalente"),
        )
    assert result == 0
    text = output.getvalue()
    assert "EQUIVALENTE N69" in text
    assert "SURVIVE N69" not in text
    assert "supervivientes: ninguno" in text


def test_todos_los_equivalentes_se_informan_sin_supervivientes():
    module = _load_harness()
    assert module.RETIRED == {}
    for mid in module.EQUIV:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert (
                module.main(
                    ["--repo", str(ROOT), "--ids", mid],
                    executor=lambda _repo, _env, _tests: (0, "equivalente"),
                )
                == 0
            )
        text = output.getvalue()
        assert f"EQUIVALENTE {mid}" in text
        assert f"SURVIVE {mid}" not in text


def test_executor_recibe_copia_byte_a_byte_y_la_copia_se_elimina(tmp_path):
    module = _load_harness()
    flight = ROOT / "scripts" / "flight"
    tmp_before = _tmp_dirs("mutate_detectors_")
    original = _tree(flight)
    seen = {}

    def executor(_repo, env, tests):
        root = Path(env["MUTATION_COPY_ROOT"])
        copy = Path(env["STALL_CHECK_UNDER_TEST"])
        copied = _tree(root)
        seen["exists"] = copy.exists()
        seen["tests"] = tests
        seen["changed"] = copy.read_bytes() != original["flight_stall_check.py"]
        assert set(copied) == set(original)
        assert all(
            copied[key] == value
            for key, value in original.items()
            if key != "flight_stall_check.py"
        )
        seen["copy_path"] = copy
        return 1, "mutant killed"

    mutation = next(item for item in module.MUT if item[0] == "E7")
    result = module.run_mutation(
        ROOT, mutation, ["tests/unit/test_flight_stall_check.py"], executor
    )
    assert result[2] == 1
    assert seen["exists"] is True
    assert seen["tests"] == ["tests/unit/test_flight_stall_check.py"]
    assert seen["changed"] is True
    assert not seen["copy_path"].exists()
    current = _tree(flight)
    assert current == original
    assert _tmp_dirs("mutate_detectors_") == tmp_before

    probe = tmp_path / "tree-probe"
    shutil.copytree(flight, probe)
    expected = _tree(flight)
    for relative in (
        Path("added.py"),
        Path("nested") / "added.py",
        Path("added.ps1"),
        Path("nested") / "added.ps1",
        Path("added.txt"),
        Path("nested") / "added.txt",
    ):
        added = probe / relative
        added.parent.mkdir(parents=True, exist_ok=True)
        added.write_bytes(b"added")
        observed = _tree(probe)
        assert observed != expected
        assert relative.as_posix() in observed
        assert relative.as_posix() not in expected
        added.unlink()
        if not any(added.parent.iterdir()):
            added.parent.rmdir()

    modified = probe / "flight_stall_check.py"
    original_bytes = modified.read_bytes()
    modified.write_bytes(original_bytes + b"\n")
    observed = _tree(probe)
    assert observed != expected
    assert observed["flight_stall_check.py"] != expected["flight_stall_check.py"]
    modified.write_bytes(original_bytes)

    deleted = probe / "flight_stall_check.py"
    deleted.unlink()
    observed = _tree(probe)
    assert observed != expected
    assert "flight_stall_check.py" not in observed

    deleted.write_bytes(original_bytes)
    ps1 = probe / "notify_user.ps1"
    ps1_original = ps1.read_bytes()
    ps1.write_bytes(ps1_original + b"\n")
    observed = _tree(probe)
    assert observed != expected
    assert observed["notify_user.ps1"] != expected["notify_user.ps1"]
    ps1.write_bytes(ps1_original)
    ps1.unlink()
    observed = _tree(probe)
    assert observed != expected
    assert "notify_user.ps1" not in observed


def test_control_no_muta_y_devuelve_rc_del_ejecutor():
    module = _load_harness()
    flight = ROOT / "scripts" / "flight"
    original = _tree(flight)
    calls = []

    def executor(_repo, env, tests):
        calls.append((env, tests))
        root = Path(env["MUTATION_COPY_ROOT"])
        copied = _tree(root)
        assert copied == original
        return 0, "control"

    assert module.main(["--repo", str(ROOT), "--control"], executor=executor) == 0
    assert len(calls) == 1
    calls.clear()

    def failing(_repo, env, tests):
        calls.append((env, tests))
        return 1, "control failed"

    assert module.main(["--repo", str(ROOT), "--control"], executor=failing) == 1
    assert len(calls) == 1


def test_focal_por_objetivo_y_tests_explicitos():
    module = _load_harness()
    seen = []

    def executor(_repo, _env, tests):
        seen.append(tests)
        return 1, "killed"

    stall = next(item for item in module.MUT if item[2] == module.STALL)
    quota = next(item for item in module.MUT if item[2] == module.QUOTA)
    module.run_mutation(ROOT, stall, None, executor)
    module.run_mutation(ROOT, quota, None, executor)
    assert seen == [
        ["tests/unit/test_flight_stall_check.py"],
        ["tests/unit/test_quota_tick.py"],
    ]
    seen.clear()
    module.run_mutation(ROOT, quota, ["tests/unit/custom.py"], executor)
    assert seen == [["tests/unit/custom.py"]]


def test_excepcion_del_ejecutor_limpia_directorio_temporal():
    module = _load_harness()
    flight = ROOT / "scripts" / "flight"
    before_tree = _tree(flight)
    before_tmp = _tmp_dirs("mutate_detectors_")
    mutation = next(item for item in module.MUT if item[0] == "E7")

    def raising(_repo, _env, _tests):
        raise RuntimeError("executor")

    try:
        module.run_mutation(ROOT, mutation, None, raising)
    except RuntimeError:
        pass
    else:
        raise AssertionError("se esperaba la excepción del ejecutor")
    assert _tree(flight) == before_tree
    assert _tmp_dirs("mutate_detectors_") == before_tmp


def test_flags_detectores_controlan_rutas_distintas():
    module = _load_harness()
    assert module.main(["--repo", str(ROOT), "--box", "nope", "--validate-only"]) == 1
    assert module.main(["--repo", str(ROOT), "--ids", "NOPE", "--validate-only"]) == 1
    assert (
        module.main(
            ["--repo", str(ROOT), "--workers", "2", "--ids", "E7"],
            executor=lambda *_: (1, "killed"),
        )
        == 0
    )
    seen = []
    assert (
        module.main(
            ["--repo", str(ROOT), "--ids", "E7", "--tests", "tests/unit/custom.py"],
            executor=lambda _repo, _env, tests: seen.append(tests) or (1, "killed"),
        )
        == 0
    )
    assert seen == [["tests/unit/custom.py"]]
