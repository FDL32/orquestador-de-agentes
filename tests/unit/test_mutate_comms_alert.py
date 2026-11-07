"""Focal tests for the versioned comms-alert mutation harness."""

import contextlib
import importlib.util
import io
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
    assert not any(item[0] == "SJ1" for item in module._selected("all", "SJ1", False))
    assert any(item[0] == "SJ1" for item in module._selected("all", "SJ1", True))


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
