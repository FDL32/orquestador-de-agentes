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
