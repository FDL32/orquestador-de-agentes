"""Contrato del guard de paridad de contratos normativos (WOT-2026-076a).

Lo que estos tests fijan:

- El ROJO REAL: un contrato normativo que diverge en contenido entre el
  checkout canonico y el worktree produce hallazgo BLOCK (exit 1), no WARN --
  consenso del bucle adversarial de 4 lentes (claude, codex, qwen3.6, gemma4)
  sobre el incidente medido: un commit (WOT-2026-039m) que cambiaba la
  secuencia de la suite canonica no se habia propagado al checkout canonico,
  y un prompt de arranque redactado desde ahi cito la secuencia obsoleta.
- El CONTROL POSITIVO: dos copias byte-identicas del mismo contrato no
  producen hallazgo, aunque vivan en raices distintas.
- HEAD del repo NO es el discriminante: dos raices con commits distintos pero
  el MISMO contenido del contrato no son un hallazgo (evita falsos positivos
  por divergencia de historia ajena a estos ficheros).
- Ausencia asimetrica (fichero solo en un lado) SI es hallazgo.
- El DENOMINADOR: siempre se publican los 3 contratos auditados, tambien en
  fallo.
"""

from __future__ import annotations

import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

from check_prompt_parity import (  # noqa: E402
    NORMATIVE_PROMPTS,
    audit,
    main,
)


def _write_contract(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_contrato_divergente_produce_hallazgo_bloqueante(tmp_path):
    """ROJO REAL: el caso medido en WOT-2026-076a -- el mismo contrato con
    texto distinto en cada raiz (secuencia pre-039m vs post-039m).
    """
    canonical = tmp_path / "canonical"
    worktree = tmp_path / "worktree"
    rel = NORMATIVE_PROMPTS[0]
    _write_contract(canonical, rel, "secuencia vieja: suite antes de Manager Review\n")
    _write_contract(worktree, rel, "secuencia nueva: suite en Paso 5-bis\n")

    findings, audited = audit(canonical, worktree)

    assert audited == list(NORMATIVE_PROMPTS)
    matching = [f for f in findings if f.rel_path == rel]
    assert len(matching) == 1, [f.render() for f in findings]
    assert matching[0].rule == "R1-contenido-diverge"


def test_contratos_identicos_no_producen_hallazgo(tmp_path):
    """CONTROL POSITIVO: sin esto, un guard que marcara CUALQUIER diferencia
    de raiz (p.ej. por HEAD de repo distinto) pasaria igual el test del rojo.
    """
    canonical = tmp_path / "canonical"
    worktree = tmp_path / "worktree"
    body = "mismo contenido exacto\n"
    for rel in NORMATIVE_PROMPTS:
        _write_contract(canonical, rel, body)
        _write_contract(worktree, rel, body)

    findings, audited = audit(canonical, worktree)

    assert findings == []
    assert audited == list(NORMATIVE_PROMPTS)


def test_ausencia_asimetrica_es_hallazgo(tmp_path):
    """Un contrato que existe en un lado y no en el otro es tan peligroso como
    uno divergente: el prompt de arranque podria citarlo sin que exista donde
    el Builder ejecuta.
    """
    canonical = tmp_path / "canonical"
    worktree = tmp_path / "worktree"
    rel = NORMATIVE_PROMPTS[1]
    _write_contract(canonical, rel, "solo existe en canonico\n")
    # worktree: no se escribe nada para `rel`.

    findings, _ = audit(canonical, worktree)

    matching = [f for f in findings if f.rel_path == rel]
    assert len(matching) == 1, [f.render() for f in findings]
    assert matching[0].rule == "R2-ausente-worktree"


def test_main_exit_1_con_hallazgos_y_denominador_publicado(tmp_path, capsys):
    """El CLI real: exit 1 si hay divergencia, y el denominador (3 contratos)
    se imprime siempre, no solo en verde.
    """
    canonical = tmp_path / "canonical"
    worktree = tmp_path / "worktree"
    for rel in NORMATIVE_PROMPTS:
        _write_contract(canonical, rel, "v1\n")
        _write_contract(worktree, rel, "v1\n")
    # Rompe solo uno, tras escribir el resto identico.
    _write_contract(worktree, NORMATIVE_PROMPTS[0], "v2 (post-039m)\n")

    exit_code = main(
        [
            "--canonical-root",
            str(canonical),
            "--worktree-root",
            str(worktree),
        ]
    )

    assert exit_code == 1
    out = capsys.readouterr()
    assert f"{len(NORMATIVE_PROMPTS)} contrato(s) auditado(s)" in out.out
    assert "1 hallazgo(s)" in out.out


def test_main_exit_0_sin_divergencia(tmp_path, capsys):
    """Verde real: los 3 contratos identicos en ambas raices -> exit 0."""
    canonical = tmp_path / "canonical"
    worktree = tmp_path / "worktree"
    for rel in NORMATIVE_PROMPTS:
        _write_contract(canonical, rel, "contenido estable\n")
        _write_contract(worktree, rel, "contenido estable\n")

    exit_code = main(
        [
            "--canonical-root",
            str(canonical),
            "--worktree-root",
            str(worktree),
        ]
    )

    assert exit_code == 0
