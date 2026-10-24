import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_contract_clause_coverage as ccc  # noqa: E402


_CONTRACT_TEXT = """# Contrato de ejemplo

## Fases

| Fase | Accion |
| --- | --- |
| uno | preparar |
| dos | ejecutar |

Esta fase exige `MANAGER_REVIEW` por ticket antes de cerrar.

- **Nonce:** obligatorio antes de cada ronda de gobierno.

**OBLIGATORIO** declarar `GROUP_STOP_REPORT` al terminar el grupo.
"""


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_extract_clause_anchors_covers_the_four_marker_kinds():
    anchors = ccc.extract_clause_anchors(_CONTRACT_TEXT)

    assert "MANAGER_REVIEW" in anchors
    assert "GROUP_STOP_REPORT" in anchors
    assert "OBLIGATORIO" in anchors
    assert "Nonce" in anchors
    assert "Fases" in anchors


def test_full_coverage_passes(tmp_path):
    contract = _write(tmp_path, "prompts/example_contract.md", _CONTRACT_TEXT)
    artifact_text = (
        "# Arranque\n\n"
        "Sigue prompts/example_contract.md: emite MANAGER_REVIEW por ticket, "
        "declara el Nonce antes de la ronda, trabaja las Fases en orden, "
        "respeta OBLIGATORIO y cierra con GROUP_STOP_REPORT.\n"
    )
    artifact = _write(tmp_path, "flight_start.md", artifact_text)

    missing = ccc.check_clause_coverage(
        artifact.read_text(encoding="utf-8"), contract.read_text(encoding="utf-8")
    )

    assert missing == []


def test_missing_keyword_fails_naming_it(tmp_path):
    contract = _write(tmp_path, "prompts/example_contract.md", _CONTRACT_TEXT)
    # GROUP_STOP_REPORT omitted on purpose.
    artifact_text = (
        "# Arranque\n\n"
        "Sigue prompts/example_contract.md: emite MANAGER_REVIEW por ticket, "
        "declara el Nonce antes de la ronda, trabaja las Fases en orden, "
        "respeta OBLIGATORIO.\n"
    )
    artifact = _write(tmp_path, "flight_start.md", artifact_text)

    missing = ccc.check_clause_coverage(
        artifact.read_text(encoding="utf-8"), contract.read_text(encoding="utf-8")
    )

    assert "GROUP_STOP_REPORT" in missing


def test_mutation_both_directions(tmp_path):
    """DoD (c): borrar una clausula obligatoria -> ROJO nombrandola; completo -> VERDE."""
    contract = _write(tmp_path, "prompts/example_contract.md", _CONTRACT_TEXT)
    full_text = (
        "# Arranque\n\n"
        "Sigue prompts/example_contract.md: emite MANAGER_REVIEW por ticket, "
        "declara el Nonce antes de la ronda, trabaja las Fases en orden, "
        "respeta OBLIGATORIO y cierra con GROUP_STOP_REPORT.\n"
    )
    contract_text = contract.read_text(encoding="utf-8")

    missing_full = ccc.check_clause_coverage(full_text, contract_text)
    assert missing_full == []

    mutated_text = full_text.replace("trabaja las Fases en orden, ", "")
    missing_mutated = ccc.check_clause_coverage(mutated_text, contract_text)
    assert "Fases" in missing_mutated

    restored_text = mutated_text.replace(
        "declara el Nonce antes de la ronda, ",
        "declara el Nonce antes de la ronda, trabaja las Fases en orden, ",
    )
    missing_restored = ccc.check_clause_coverage(restored_text, contract_text)
    assert missing_restored == []


def test_routing_citation_counts_as_coverage_without_duplicating_text(tmp_path):
    """DoD (d): nombrar la clausula y su fuente basta; no hace falta copiar el texto."""
    contract = _write(tmp_path, "prompts/example_contract.md", _CONTRACT_TEXT)
    # No reproduce la tabla de Fases ni el texto normativo: solo ENRUTA.
    artifact_text = (
        "# Arranque\n\n"
        "Este prompt ENRUTA al contrato: ver prompts/example_contract.md para "
        "MANAGER_REVIEW, Nonce, Fases, OBLIGATORIO y GROUP_STOP_REPORT -- no se "
        "reproduce aqui su texto completo.\n"
    )
    artifact = _write(tmp_path, "flight_start_routed.md", artifact_text)

    missing = ccc.check_clause_coverage(
        artifact.read_text(encoding="utf-8"), contract.read_text(encoding="utf-8")
    )

    assert missing == []


def test_near_token_does_not_mask_a_missing_anchor(tmp_path):
    """Revisor (modo 3): un substring sin bordes dejaba que BUILDER_EXITS
    satisficiera el anchor BUILDER_EXIT. Fijado con \\b en _anchor_is_present."""
    contract_text = "# Contrato\n\nDeclara `BUILDER_EXIT` antes de cerrar el ticket.\n"
    # El artefacto solo menciona el casi-token, nunca el anchor real.
    artifact_text = (
        "Este prompt habla de BUILDER_EXITS en plural, nunca del singular.\n"
    )

    missing = ccc.check_clause_coverage(artifact_text, contract_text)

    assert "BUILDER_EXIT" in missing


def test_zero_anchors_contract_prints_warning_not_ok(tmp_path, capsys):
    """Revisor (modo 3): un contrato sin anclajes extraibles no debe reportarse
    como 'OK: cubre...' -- no hay nada que cubrir, y eso no es lo mismo."""
    _write(
        tmp_path,
        "prompts/no_anchors.md",
        "# Contrato sin marcadores\n\nTexto de prosa llana, sin tablas ni enfasis.\n",
    )
    artifact = _write(tmp_path, "flight_start.md", "Sigue prompts/no_anchors.md.\n")

    rc = ccc.main(["--artifact", str(artifact), "--project-root", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "no verificable" in out.lower()


def test_no_contracts_cited_is_noop(tmp_path):
    artifact = _write(
        tmp_path, "standalone.md", "# Nada que citar\n\nTexto sin rutas de contrato.\n"
    )

    contracts = ccc.extract_cited_contracts(
        artifact.read_text(encoding="utf-8"), tmp_path
    )

    assert contracts == []


def test_auto_detect_finds_cited_contract_path(tmp_path):
    _write(tmp_path, "prompts/example_contract.md", _CONTRACT_TEXT)
    artifact_text = "Sigue prompts/example_contract.md para el detalle.\n"
    artifact = _write(tmp_path, "flight_start.md", artifact_text)

    contracts = ccc.extract_cited_contracts(
        artifact.read_text(encoding="utf-8"), tmp_path
    )

    assert len(contracts) == 1
    assert contracts[0] == (tmp_path / "prompts" / "example_contract.md").resolve()


def test_main_cli_exits_1_naming_missing_anchor(tmp_path, capsys):
    _write(tmp_path, "prompts/example_contract.md", _CONTRACT_TEXT)
    artifact_text = (
        "Sigue prompts/example_contract.md: emite MANAGER_REVIEW, declara el "
        "Nonce, trabaja las Fases, respeta OBLIGATORIO.\n"
    )
    artifact = _write(tmp_path, "flight_start.md", artifact_text)

    rc = ccc.main(["--artifact", str(artifact), "--project-root", str(tmp_path)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "GROUP_STOP_REPORT" in err


def test_main_cli_exits_0_when_no_contract_cited(tmp_path, capsys):
    artifact = _write(tmp_path, "standalone.md", "# Nada que citar\n")

    rc = ccc.main(["--artifact", str(artifact), "--project-root", str(tmp_path)])

    assert rc == 0
