"""WOT-2026-104e: el cierre no debe poder declarar "Block 2.5 limpio" sin
que exista NINGUNA evidencia de que se registro una propuesta 2.5.j (PROCESS
IMPROVEMENT PROPOSAL, prompts/orchestrator_session_close_full_audit.md:
273-276) cuando el propio cierre SI emitio WARN en otros pasos -- gap medido
en vivo en la sesion continuacion-wot-2026-102a (2026-10-18): tres rondas de
friccion real de cierre (recibos de backlog-admission, delivery_authority
ausente tras archivado) no generaron ninguna propuesta 2.5.j, y nada lo
habria detectado.

Mutation-verified: `_step_process_improvement_coverage` es pura sobre
(steps_so_far, contenido de execution_log.md). Tres casos discriminan:
sin WARN previos -> PASS sin mirar el log; con WARN previos y SIN marcador
-> WARN; con WARN previos y CON marcador -> PASS.
"""

from __future__ import annotations

import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts import session_closeout as sc  # noqa: E402


def _warn_step(name: str) -> sc.StepResult:
    return sc.StepResult(name=name, status="WARN", detail="algo paso")


def _pass_step(name: str) -> sc.StepResult:
    return sc.StepResult(name=name, status="PASS", detail="ok")


def test_no_warn_previos_pasa_sin_mirar_el_log(tmp_path: Path) -> None:
    """Sin WARN previos no hay nada que exigir: PASS incluso sin execution_log.md."""
    result = sc._step_process_improvement_coverage(
        tmp_path, [_pass_step("prepush_check")]
    )
    assert result.status == "PASS"
    assert result.name == "process_improvement_coverage"


def test_warn_previo_sin_marcador_produce_warn(tmp_path: Path) -> None:
    """CONTROL POSITIVO: hubo WARN y el log no tiene ningun marcador 2.5.j -> WARN."""
    elog = tmp_path / ".agent" / "collaboration" / "execution_log.md"
    elog.parent.mkdir(parents=True)
    elog.write_text(
        "# Execution Log\n\nSin ninguna mencion de proceso.\n", encoding="utf-8"
    )
    result = sc._step_process_improvement_coverage(
        tmp_path, [_warn_step("memory_health"), _pass_step("git_clean")]
    )
    assert result.status == "WARN"
    assert "POSIBLE_2.5J_RUBBER_STAMP" in result.detail
    assert "memory_health" in result.detail


def test_warn_previo_con_tag_proceso_cierre_pasa(tmp_path: Path) -> None:
    """CONTROL: el mismo WARN previo, pero el log SI tiene el prefijo -> PASS."""
    elog = tmp_path / ".agent" / "collaboration" / "execution_log.md"
    elog.parent.mkdir(parents=True)
    elog.write_text(
        "# Execution Log\n\n- [PROCESO-CIERRE] friccion de recibos registrada.\n",
        encoding="utf-8",
    )
    result = sc._step_process_improvement_coverage(
        tmp_path, [_warn_step("memory_health")]
    )
    assert result.status == "PASS"


def test_warn_previo_con_marcador_sin_hallazgos_pasa(tmp_path: Path) -> None:
    """CONTROL: el marcador explicito de sin-hallazgos tambien satisface el gate."""
    elog = tmp_path / ".agent" / "collaboration" / "execution_log.md"
    elog.parent.mkdir(parents=True)
    elog.write_text(
        "# Execution Log\n\n2.5.j: sin_hallazgos_declarado -- nada nuevo esta sesion.\n",
        encoding="utf-8",
    )
    result = sc._step_process_improvement_coverage(
        tmp_path, [_warn_step("validate_ticket_prose")]
    )
    assert result.status == "PASS"


def test_execution_log_ausente_con_warn_previo_produce_warn(tmp_path: Path) -> None:
    """Sin execution_log.md en disco (OSError) y con WARN previo: WARN, nunca excepcion."""
    result = sc._step_process_improvement_coverage(
        tmp_path, [_warn_step("memory_health")]
    )
    assert result.status == "WARN"


def test_marcador_sin_hallazgos_sin_justificacion_sigue_en_warn(tmp_path: Path) -> None:
    """Hallazgo real ronda 2 (DBL-4, kilo_deepseek BA07): el marcador DESNUDO
    (sin ``-- <justificacion>`` no vacia) no satisface el gate -- es el fix de
    ronda 1 que el codigo original afirmaba aplicado y no lo estaba."""
    elog = tmp_path / ".agent" / "collaboration" / "execution_log.md"
    elog.parent.mkdir(parents=True)
    elog.write_text(
        "# Execution Log\n\n2.5.j: sin_hallazgos_declarado\n", encoding="utf-8"
    )
    result = sc._step_process_improvement_coverage(
        tmp_path, [_warn_step("memory_health")]
    )
    assert result.status == "WARN"


def test_tag_citado_dentro_de_bloque_de_codigo_no_cuenta(tmp_path: Path) -> None:
    """Hallazgo real ronda 2: una cita/ejemplo dentro de un fence ``` no debe
    producir un PASS falso -- el match se busca DESPUES de stripear fences,
    igual que scripts/check_process_decision_search.py."""
    elog = tmp_path / ".agent" / "collaboration" / "execution_log.md"
    elog.parent.mkdir(parents=True)
    elog.write_text(
        "# Execution Log\n\n"
        "Ejemplo de convencion:\n```\n[PROCESO-CIERRE] esto es solo un ejemplo citado\n```\n",
        encoding="utf-8",
    )
    result = sc._step_process_improvement_coverage(
        tmp_path, [_warn_step("memory_health")]
    )
    assert result.status == "WARN"
