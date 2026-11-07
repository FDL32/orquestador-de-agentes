"""Focal tests for the versioned comms-alert mutation harness.

Formas de entrada -> test:
objetivo ausente/OSError -> test_fichero_ausente_se_rechaza_por_main_rc_1;
bytes UTF-8 inválidos -> test_main_rechaza_objetivo_ilegible_por_unicodeerror_rc_1;
0 coincidencias -> test_main_rechaza_patron_inexistente_por_rc_1;
2 coincidencias -> test_main_rechaza_patron_duplicado_por_rc_1;
mutante igual -> test_main_rechaza_mutacion_igual_por_rc_1;
no compila -> test_main_rechaza_mutacion_no_compilable_por_rc_1;
id duplicado -> test_validate_rechaza_id_duplicado_sin_otro_motivo;
tabla vacía -> test_empty_table_is_not_vacuously_green;
caja o id desconocido -> test_flags_comms_controlan_rutas_distintas.
"""

import contextlib
import importlib.util
import io
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "mutate_comms_alert.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "mutate_comms_alert_under_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_import_has_no_cli_side_effects():
    module = _load()
    assert module.RETIRED == {}
    assert len(module.MUT) == 130


def test_validate_only_covers_current_patterns_and_retired_reasons():
    module = _load()
    selected = module._selected("all", "", visible=True)
    assert len(selected) == 130
    assert all(item[0] not in module.RETIRED for item in selected)
    assert set(module.REANCHORED) == {
        "N1",
        "N2",
        "E2",
        "N7",
        "X14",
        "N30",
        "N31",
        "N32",
        "D19b",
        "N38",
        "N42",
        "N44",
        "N46",
        "D15a",
        "Q4a",
        "N50",
        "N54",
        "N56b",
        "N56c",
        "N57",
        "SJ3",
        "B1a",
        "B1c",
        "C1a",
    }
    assert all(reason.strip() for reason in module.REANCHORED.values())
    assert module.validate(ROOT, selected) == []
    assert module.main(["--repo", str(ROOT), "--validate-only", "--visible"]) == 0


def test_bad_pattern_is_a_control_negative(capsys):
    module = _load()
    rc = module.main(["--repo", str(ROOT), "--validate-only", "--inject-bad-pattern"])
    assert rc == 1
    assert "BAD" in capsys.readouterr().out


def test_empty_table_is_not_vacuously_green(monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "MUT", [])
    assert module.main(["--repo", str(ROOT), "--validate-only"]) == 1


def test_injected_executor_runs_on_copy_and_cleans_it():
    module = _load()
    original = (ROOT / "scripts" / "flight" / "comms_alert.py").read_bytes()
    seen = {}

    def executor(repo, env, tests):
        copy = Path(env["COMMS_ALERT_UNDER_TEST"])
        seen["exists"] = copy.exists()
        seen["tests"] = tests
        seen["changed"] = copy.read_bytes() != original
        seen["copy_path"] = copy
        return 1, "mutant killed"

    mutation = module._selected("1A", "E1", visible=False)[0]
    result = module.run_mutation(
        ROOT, mutation, ["tests/unit/test_comms_alert.py"], executor
    )
    assert result[2] == 1
    assert seen["exists"] is True
    assert seen["tests"] == ["tests/unit/test_comms_alert.py"]
    assert seen["changed"] is True
    assert not seen["copy_path"].exists()
    assert (ROOT / "scripts" / "flight" / "comms_alert.py").read_bytes() == original


def test_timeout_is_not_a_kill_and_is_not_green():
    module = _load()

    def timeout(_repo, _env, _tests):
        return 99, "CRASH-TIMEOUT"

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = module.main(["--repo", str(ROOT), "--ids", "E1"], executor=timeout)
    assert rc == 1
    assert "TIMEOUT E1" in output.getvalue()
    assert "matadas 0/1" in output.getvalue()
    assert "errores: ninguno" in output.getvalue()


def test_visible_mutations_are_opt_in_even_when_selected_by_id():
    module = _load()
    visible_ids = {"SJ1", "N56b", "N56c"}
    for mid in visible_ids:
        assert not any(item[0] == mid for item in module._selected("all", "", False))
        assert not any(item[0] == mid for item in module._selected("all", mid, False))
        assert any(item[0] == mid for item in module._selected("all", mid, True))
    ordinary = next(item[0] for item in module.MUT if item[0] not in visible_ids)
    assert any(item[0] == ordinary for item in module._selected("all", ordinary, False))


def _tree(root):
    """Devuelve el árbol completo de ficheros con bytes y rutas relativas."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _tmp_dirs(prefix):
    """Cuenta directorios temporales vivos del arnés por prefijo."""
    return {
        path for path in Path(tempfile.gettempdir()).glob(prefix + "*") if path.is_dir()
    }


def test_main_rechaza_patron_inexistente_por_rc_1(tmp_path):
    module = _load()
    repo = _synthetic_repo(tmp_path)
    module.MUT = _synthetic(module, "MAIN0", "missing", "x")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_rechaza_patron_duplicado_por_rc_1(tmp_path):
    module = _load()
    repo = _synthetic_repo(tmp_path, "abcabc")
    module.MUT = _synthetic(module, "MAIN2", "abc", "x")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_rechaza_mutacion_igual_por_rc_1(tmp_path):
    module = _load()
    repo = _synthetic_repo(tmp_path)
    module.MUT = _synthetic(module, "MAIN3", "abc", "abc")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_rechaza_mutacion_no_compilable_por_rc_1(tmp_path):
    module = _load()
    repo = _synthetic_repo(tmp_path, "value = 1")
    module.MUT = _synthetic(module, "MAIN4", "value = 1", "if (")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_fichero_ausente_se_rechaza_por_main_rc_1(tmp_path):
    module = _load()
    repo = _synthetic_repo(tmp_path)
    module.MUT = _synthetic(module, "MAIN6", "abc", "x", "missing.py")
    assert module.main(["--repo", str(repo), "--validate-only"]) == 1


def test_main_rechaza_objetivo_ilegible_por_unicodeerror_rc_1(capsys, tmp_path):
    module = _load()
    repo = _synthetic_repo(tmp_path)
    (repo / "scripts" / "flight" / "comms_alert.py").write_bytes(b"\xff\xfe")
    module.MUT = _synthetic(module, "W1", "x", "y")

    def executor(*_args):
        raise AssertionError("executor")

    assert module.main(["--repo", str(repo), "--validate-only"], executor) == 1
    output = capsys.readouterr().out
    assert "W1" in output and "no se puede leer" in output


def test_formas_de_entrada_documentadas_existen():
    names = (
        "test_fichero_ausente_se_rechaza_por_main_rc_1",
        "test_main_rechaza_objetivo_ilegible_por_unicodeerror_rc_1",
        "test_main_rechaza_patron_inexistente_por_rc_1",
        "test_main_rechaza_patron_duplicado_por_rc_1",
        "test_main_rechaza_mutacion_igual_por_rc_1",
        "test_main_rechaza_mutacion_no_compilable_por_rc_1",
        "test_validate_rechaza_id_duplicado_sin_otro_motivo",
        "test_empty_table_is_not_vacuously_green",
        "test_flags_comms_controlan_rutas_distintas",
    )
    for name in names:
        assert callable(getattr(sys.modules[__name__], name))


def test_copia_completa_byte_a_byte_y_control_positivo(tmp_path):
    module = _load()
    original = _tree(ROOT / "scripts" / "flight")
    seen = {}

    def executor(_repo, env, tests):
        copied = _tree(Path(env["MUTATION_COPY_ROOT"]))
        target = "comms_alert.py"
        seen["tests"] = tests
        assert set(copied) == set(original)
        assert all(
            copied[key] == value for key, value in original.items() if key != target
        )
        assert copied[target] != original[target]
        assert _tree(ROOT / "scripts" / "flight") == original
        return 1, "killed"

    before = _tree(ROOT / "scripts" / "flight")
    tmp_before = _tmp_dirs("mutate_comms_")
    mutation = module._selected("1A", "E1", visible=False)[0]
    module.run_mutation(ROOT, mutation, None, executor)
    assert seen["tests"] == ["tests/unit/test_comms_alert.py"]
    assert _tree(ROOT / "scripts" / "flight") == before
    assert _tmp_dirs("mutate_comms_") == tmp_before

    probe = tmp_path / "tree-probe"
    shutil.copytree(ROOT / "scripts" / "flight", probe)
    expected = _tree(ROOT / "scripts" / "flight")
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

    modified = probe / "comms_alert.py"
    original_bytes = modified.read_bytes()
    modified.write_bytes(original_bytes + b"\n")
    assert _tree(probe) != expected
    assert _tree(probe)["comms_alert.py"] != expected["comms_alert.py"]
    modified.write_bytes(original_bytes)

    deleted = probe / "comms_alert.py"
    deleted.unlink()
    observed = _tree(probe)
    assert observed != expected
    assert "comms_alert.py" not in observed

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


def test_validate_ps1_no_compila_y_main_anuncia_limite(capsys, monkeypatch, tmp_path):
    module = _load()
    repo = _synthetic_repo(tmp_path)
    ps1 = repo / "scripts" / "flight" / "notify_user.ps1"
    ps1.write_text("Write-Host old\n", encoding="utf-8")
    mutation = ("PS1", "synthetic", "notify_user.ps1", "old", "new")

    def forbidden_compile(*_args, **_kwargs):
        raise AssertionError("validate no debe compilar PowerShell")

    monkeypatch.setattr("builtins.compile", forbidden_compile)
    module.MUT = [mutation]
    assert module.validate(repo, [mutation]) == []
    assert module.main(["--repo", str(repo), "--validate-only"]) == 0
    output = capsys.readouterr().out
    assert (
        "casa 1 vez y difiere; los .py compilan; los .ps1 NO se compilan "
        "(limite declarado)"
    ) in output


def test_run_mutation_control_preserva_copia_y_ejecuta_una_vez():
    module = _load()
    before = _tree(ROOT / "scripts" / "flight")
    tmp_before = _tmp_dirs("mutate_comms_")
    calls = []

    def executor(_repo, env, tests):
        calls.append((env, tests))
        copied = _tree(Path(env["MUTATION_COPY_ROOT"]))
        assert copied == before
        return 0, "control"

    control = ("CONTROL", "-", "comms_alert.py", None, None)
    result = module.run_mutation(ROOT, control, None, executor)

    assert result[:3] == ("CONTROL", "-", 0)
    assert len(calls) == 1
    assert calls[0][1] == ["tests/unit/test_comms_alert.py"]
    assert _tree(ROOT / "scripts" / "flight") == before
    assert _tmp_dirs("mutate_comms_") == tmp_before


def test_ejecutor_inyectado_recibe_tests_explicitos_y_excepcion_limpia():
    module = _load()
    baseline = _tree(ROOT / "scripts" / "flight")
    tmp_before = _tmp_dirs("mutate_comms_")
    seen = {}

    def executor(_repo, env, tests):
        seen["tests"] = tests
        assert _tree(Path(env["MUTATION_COPY_ROOT"]))
        raise RuntimeError("ejecutor")

    mutation = module._selected("1A", "E1", visible=False)[0]
    try:
        module.run_mutation(ROOT, mutation, ["tests/unit/test_custom.py"], executor)
    except RuntimeError:
        pass
    else:
        raise AssertionError("se esperaba la excepción del ejecutor")
    assert seen["tests"] == ["tests/unit/test_custom.py"]
    assert _tree(ROOT / "scripts" / "flight") == baseline
    assert _tmp_dirs("mutate_comms_") == tmp_before


def test_flags_comms_controlan_rutas_distintas():
    module = _load()
    assert module.main(["--repo", str(ROOT), "--box", "nope", "--validate-only"]) == 1
    assert module.main(["--repo", str(ROOT), "--ids", "NOPE", "--validate-only"]) == 1
    seen = []
    assert (
        module.main(
            ["--repo", str(ROOT), "--ids", "E1", "--tests", "tests/unit/custom.py"],
            executor=lambda _repo, _env, tests: seen.append(tests) or (1, "killed"),
        )
        == 0
    )
    assert seen == [["tests/unit/custom.py"]]


def _synthetic_repo(tmp_path, text="abc"):
    """Crea una raíz mínima para probar una sola barrera de validación."""
    flight = tmp_path / "scripts" / "flight"
    flight.mkdir(parents=True)
    (flight / "comms_alert.py").write_text(text, encoding="utf-8")
    return tmp_path


def _synthetic(module, mid, pattern, replacement, target="comms_alert.py"):
    return [(mid, "synthetic", target, pattern, replacement)]


def test_validate_rechaza_patron_inexistente_sin_otro_motivo(tmp_path):
    module = _load()
    errors = module.validate(
        _synthetic_repo(tmp_path), _synthetic(module, "H1", "missing", "x")
    )
    assert len(errors) == 1 and "casa 0" in errors[0]


def test_validate_rechaza_patron_duplicado_sin_otro_motivo(tmp_path):
    module = _load()
    errors = module.validate(
        _synthetic_repo(tmp_path, "abcabc"), _synthetic(module, "H2", "abc", "x")
    )
    assert len(errors) == 1 and "casa 2" in errors[0]


def test_validate_rechaza_mutacion_igual_sin_otro_motivo(tmp_path):
    module = _load()
    errors = module.validate(
        _synthetic_repo(tmp_path), _synthetic(module, "H3", "abc", "abc")
    )
    assert errors == ["H3: la mutacion no difiere del original"]


def test_validate_rechaza_mutacion_no_compilable_sin_otro_motivo(tmp_path):
    module = _load()
    errors = module.validate(
        _synthetic_repo(tmp_path, "value = 1"),
        _synthetic(module, "H4", "value = 1", "if ("),
    )
    assert len(errors) == 1 and "no compila" in errors[0]


def test_validate_rechaza_id_duplicado_sin_otro_motivo(tmp_path):
    module = _load()
    mutations = _synthetic(module, "H5", "a", "x") + _synthetic(module, "H5", "b", "y")
    errors = module.validate(_synthetic_repo(tmp_path, "ab"), mutations)
    assert errors == ["H5: id duplicado"]


def test_validate_rechaza_fichero_ausente_sin_otro_motivo(tmp_path):
    module = _load()
    errors = module.validate(
        _synthetic_repo(tmp_path), _synthetic(module, "H6", "abc", "x", "missing.py")
    )
    assert len(errors) == 1 and "no se puede leer" in errors[0]


def test_executor_rc_5_y_rc_2_son_errores_no_muertes():
    module = _load()
    for rc in (5, 2):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = module.main(
                ["--repo", str(ROOT), "--ids", "E1"],
                executor=lambda _repo, _env, _tests, rc=rc: (rc, "bad executor"),
            )
        text = output.getvalue()
        assert result == 1
        assert "ERROR E1" in text
        assert "matadas 0/1" in text


def test_rc_0_es_superviviente_no_adjudicado():
    module = _load()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = module.main(
            ["--repo", str(ROOT), "--ids", "E1"],
            executor=lambda _repo, _env, _tests: (0, "green"),
        )
    assert result == 1
    assert "SURVIVE E1" in output.getvalue()
