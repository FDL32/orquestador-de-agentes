"""Coherencia entre el registro v2 y sus consumidores documentales."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from scripts import check_ensemble_registry_classification as cec


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / ".agent" / "config" / "agents.json"
PROMPT_PATH = ROOT / "prompts" / "ensemble_loop.md"


def _config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _doc_rows(text: str) -> dict[str, str]:
    """Filas `| celda | nivel |` del prompt; cabeceras y separadores fuera."""
    rows: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        first = cells[0]
        if first in ("Referencia", "") or set(first) <= {"-"}:
            continue
        rows[first] = cells[1].strip("`")
    return rows


def cell_findings(text: str, config: dict) -> list[str]:
    """Celdas del prompt que divergen del registro (t2-d05: 1 tabla, 1 coherencia).

    Before: `text` es el contenido del prompt (vivo o copia mutada) y `config`
        el agents.json correspondiente (vivo o copia).
    During: compara la celda de glm5.3 y la del REVISOR del IM/TR contra los
        niveles del registro, y exige que role_mapping.revisor y
        role_models.REVISOR declaren el mismo model_id (cambio IM/TR).
    After: lista de hallazgos; vacia = coherente. Solo lectura.
    """
    findings: list[str] = []
    registry = config.get("ensemble_registry", {})
    backend_keys = registry.get("backend_keys", {})
    rows = _doc_rows(text)

    glm_cell = next((v for k, v in rows.items() if "nan/glm5.3" in k), None)
    glm_entries = [
        entry
        for entry in backend_keys.values()
        if entry.get("model") == "nan/glm5.3" and entry.get("status") == "active"
    ]
    if not glm_entries:
        findings.append("registro sin clave activa nan/glm5.3")
    elif glm_cell is None or any(e.get("nivel") != glm_cell for e in glm_entries):
        findings.append(
            f"celda nan/glm5.3={glm_cell!r} != nivel del registro "
            f"{[e.get('nivel') for e in glm_entries]}"
        )

    revisor_model = config.get("role_models", {}).get("REVISOR")
    rev_cell = next(
        (v for k, v in rows.items() if revisor_model and revisor_model in k), None
    )
    rev_entries = [
        entry for entry in backend_keys.values() if entry.get("model") == revisor_model
    ]
    if not revisor_model or rev_cell is None or not rev_entries:
        findings.append("celda del REVISOR ausente en el prompt o model_id sin clave")
    elif any(e.get("nivel") != rev_cell for e in rev_entries):
        findings.append(
            f"celda REVISOR={rev_cell!r} != nivel del registro "
            f"{[e.get('nivel') for e in rev_entries]}"
        )

    mapping_model = config.get("role_mapping", {}).get("revisor", {}).get("model")
    if mapping_model != revisor_model:
        findings.append(
            f"cambio IM/TR sin sincronizar: role_mapping.revisor.model="
            f"{mapping_model!r} != role_models.REVISOR={revisor_model!r}"
        )
    return findings


def test_prompt_remits_to_the_single_flat_usage_table():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "ensemble_registry.uso_maximo_por_tipo" in text
    assert "agents.json" in text
    for level in _config()["ensemble_registry"]["uso_maximo_por_tipo"]:
        assert f"`{level}`" in text


def test_usage_table_mutation_is_detected_by_the_registry_lint():
    config = _config()
    mutated = copy.deepcopy(config)
    mutated["ensemble_registry"]["uso_maximo_por_tipo"]["alto"] = -1
    errors = cec.lint_registry(mutated)
    assert any("uso_maximo_por_tipo.alto" in error for error in errors)


@pytest.mark.parametrize("level", ["base", "medio", "alto", "premium"])
def test_usage_table_values_are_finite_non_negative_numbers(level):
    value = _config()["ensemble_registry"]["uso_maximo_por_tipo"][level]
    assert isinstance(value, (int, float))
    assert value >= 0
    assert value != float("inf")


def test_doc_cells_match_registry_levels():
    """La tabla del prompt remite al registro: 1 tabla + 1 coherencia (t2-d05)."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert cell_findings(text, _config()) == []


def test_doc_cell_glm53_mutation_is_red():
    """Control: mutar la celda de glm5.3 en una copia del prompt -> hallazgo."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    mutated = text.replace(
        "| `nan/glm5.3` (BA255/BA268) | `premium` |",
        "| `nan/glm5.3` (BA255/BA268) | `alto` |",
    )
    # Si el fichero ya viene mutado (control externo sobre copia), el texto
    # actual ya diverge y el hallazgo tiene que aparecer igualmente.
    target = mutated if mutated != text else text
    assert cell_findings(target, _config()), "la celda mutada debe producir rojo"


def test_im_tr_revisor_mutation_is_red():
    """Control: cambio IM/TR (role_mapping.revisor) en una copia -> hallazgo."""
    config = _config()
    config["role_mapping"]["revisor"]["model"] = "nan/glm5.3-flash"
    assert cell_findings(PROMPT_PATH.read_text(encoding="utf-8"), config)


def test_role_models_revisor_mutation_is_red():
    """Control: cambio de role_models.REVISOR en una copia -> hallazgo."""
    config = _config()
    config["role_models"]["REVISOR"] = "nan/glm5.3-flash"
    assert cell_findings(PROMPT_PATH.read_text(encoding="utf-8"), config)


def _load_t1():
    """Carga scripts/flight/flight_stall_check.py como su propia suite lo hace."""
    import importlib.util

    path = ROOT / "scripts" / "flight" / "flight_stall_check.py"
    spec = importlib.util.spec_from_file_location("flight_stall_check_221b_ut", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_t1_real_reader_consumes_the_single_table(monkeypatch, tmp_path):
    """El T1 INTEGRADO lee la MISMA tabla unica desde una copia mutada.

    Before: dos copias de agents.json en tmp_path (una con el techo de `alto`
        mutado a 1234, otra sin `uso_maximo_por_tipo`); NAN_AGENTS_JSON apunta
        a la copia, nunca al arbol vivo.
    During: `_nan_agents_registry` devuelve el techo mutado de la copia y
        `_nan_metadata` lo hace fluir como `cap` del registro que T1 escribe en
        su recibo atomico; la copia sin la tabla devuelve `techo-ausente`
        (fail-closed: T1 no inventa techo ni nivel).
    After: el techo y el nivel que T1 recibe son los de la fuente unica; sin
        tabla no hay techo. (Condicion CO-160 2026-11-23; t2-d05.)
    """
    t1 = _load_t1()
    cfg = _config()
    cfg["ensemble_registry"]["uso_maximo_por_tipo"]["alto"] = 1234
    copy_path = tmp_path / "agents_con_techo.json"
    copy_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("NAN_AGENTS_JSON", str(copy_path))
    ceilings, status = t1._nan_agents_registry()
    assert status is None, status
    assert ceilings["alto"] == 1234.0
    levels, _auths, cap, _user_request, _rate = t1._nan_metadata(
        [{"nivel": "alto", "autorizacion": "auth-1"}], ceilings
    )
    assert cap == 1234.0
    assert "alto" in levels  # el nivel que viaja en el recibo de T1

    bare = tmp_path / "agents_sin_techo.json"
    bare.write_text(json.dumps({"ensemble_registry": {}}), encoding="utf-8")
    monkeypatch.setenv("NAN_AGENTS_JSON", str(bare))
    assert t1._nan_agents_registry() == ({}, "techo-ausente")


def test_per_key_ceiling_redefinition_is_red_by_the_lint():
    """Ninguna clave redefine el techo: su `uso_maximo` es una referencia.

    Before: registro real (vivo, solo lectura) + copia mutada cuya primera
        clave activa pasa a llevar un techo NUMERICO en `uso_maximo`.
    During: el lint v2 exige que `uso_maximo` referencie un nivel valido
        (string); hoy ninguna clave activa alberga un techo numerico, porque
        la unica fuente numerica es `uso_maximo_por_tipo`.
    After: la mutacion produce un hallazgo que nombra la clave y el campo; la
        pristine queda sin hallazgos. (Condicion CO-160 2026-11-23; t2-d05.)
    """
    config = _config()
    backend_keys = config["ensemble_registry"]["backend_keys"]
    active_keys = [
        key for key, entry in backend_keys.items() if entry.get("status") == "active"
    ]
    assert active_keys
    for key in active_keys:
        assert isinstance(backend_keys[key]["uso_maximo"], str), key

    mutated = copy.deepcopy(config)
    target = active_keys[0]
    mutated["ensemble_registry"]["backend_keys"][target]["uso_maximo"] = 9999
    errors = cec.lint_registry(mutated)
    assert any(target in e and "uso_maximo" in e for e in errors), errors
    assert cec.lint_registry(config) == []
