"""State-file validation: pure content -> errors checks for --validate.

Extracted from agent_controller.py (monolith decomposition). This module
owns the markdown state validators and their parsing helpers:

- Status/ID extraction from canonical markdown (work_plan, execution_log).
- Per-file format validation (valid states, required fields, corruption).
- Cross-file drift detection (plan vs log impossible state combinations).

Every function takes file CONTENT as input and returns a list of error
strings — no filesystem access, no module globals. agent_controller keeps
thin wrappers that read the files and pass content here, so its globals
(read_file, lazy paths) remain the test seam.
"""

from __future__ import annotations


# Estados validos para validacion
VALID_PLAN_STATES = {
    "DRAFT",
    "IN_PLANNING",
    "APPROVED",
    "IN_REVIEW",
    "COMPLETED",
    "N/A",
    "READY_TO_START",
}
VALID_LOG_STATES = {
    "PENDING",
    "IN_PROGRESS",
    "BLOCKED",
    "READY_FOR_REVIEW",
    # WP-2026-106: HUMAN_GATE and READY_TO_CLOSE are real terminal-adjacent
    # states emitted by bus/state_machine.py; the validator must accept them.
    "HUMAN_GATE",
    "READY_TO_CLOSE",
    "COMPLETED",
    "N/A",
    "READY_TO_START",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def get_status(content: str, marker: str) -> str:
    """Extrae el estado de un archivo buscando un marcador."""
    for line in content.split("\n"):
        if marker in line:
            return line.split(marker)[1].strip()
    return "UNKNOWN"


def get_plan_id(content: str) -> str:
    """Extrae el ID del plan de trabajo."""
    for line in content.split("\n"):
        if "**ID:**" in line or "**Plan ID:**" in line:
            return line.split(":**")[1].strip()
    return "N/A"


def get_plan_type(content: str) -> str:
    """Extrae el tipo de plan. Valores: IMPLEMENTATION (default) | FINALIZATION."""
    for line in content.split("\n"):
        if "**Tipo:**" in line:
            return line.split(":**")[1].strip().upper()
    return "IMPLEMENTATION"


def extract_status_emoji(status_str: str) -> tuple[str, str]:
    """Extrae el estado limpio y el emoji."""
    emojis = {"🟢", "🟡", "🔴", "🟣", "✅", "⏳", "❌", "⚠️"}
    status_clean = status_str.strip()
    found_emoji = ""
    for emoji in emojis:
        if emoji in status_clean:
            found_emoji = emoji
            status_clean = status_clean.replace(emoji, "").strip()
            break
    return status_clean, found_emoji


def is_seed_neutral_state(plan_content: str, log_content: str) -> bool:
    """Return True when the motor collaboration seed has no active ticket.

    The portable motor ships a neutral seed under ``repo_motor/.agent/collaboration/``.
    That seed is documented as ``ID=none`` with ``READY_TO_START`` projections and
    must validate cleanly even though no ticket/bus lifecycle exists yet.
    """
    plan_id = get_plan_id(plan_content).strip().lower()
    plan_status, _ = extract_status_emoji(get_status(plan_content, "**Estado:**"))
    log_status, _ = extract_status_emoji(get_status(log_content, "**Estado:**"))
    return (
        plan_id == "none"
        and plan_status == "READY_TO_START"
        and log_status == "READY_TO_START"
    )


# ---------------------------------------------------------------------------
# Per-file validators (content -> errors)
# ---------------------------------------------------------------------------


def validate_work_plan_content(content: str) -> list[str]:
    """Validate work_plan.md content."""
    errors: list[str] = []
    if not content:
        return errors

    status_raw = get_status(content, "**Estado:**")
    status_clean, _ = extract_status_emoji(status_raw)
    if status_clean and status_clean not in VALID_PLAN_STATES:
        errors.append(f"Estado invalido: '{status_clean}'")
    if "**ID:**" not in content:
        errors.append("Falta campo **ID:**")
    return errors


def validate_execution_log_content(content: str) -> list[str]:
    """Validate execution_log.md content."""
    errors: list[str] = []
    if not content:
        return errors

    status_raw = get_status(content, "**Estado:**")
    status_clean, _ = extract_status_emoji(status_raw)
    if status_clean and status_clean not in VALID_LOG_STATES:
        errors.append(f"Estado invalido: '{status_clean}'")
    return errors


def validate_turn_content(content: str) -> list[str]:
    """Validate TURN.md content."""
    errors: list[str] = []
    if content and "## Agente Activo" not in content:
        errors.append("Falta sección '## Agente Activo'")
    return errors


def validate_notifications_content(content: str) -> list[str]:
    """Validate notifications.md content."""
    errors: list[str] = []
    if content and "</thinking>" in content:
        errors.append("Contiene etiquetas </thinking> (corrupto)")
    return errors


# ---------------------------------------------------------------------------
# Cross-file drift detection
# ---------------------------------------------------------------------------


def validate_cross_file_consistency(plan_content: str, log_content: str) -> list[str]:
    """Detect impossible plan/log state combinations (drift)."""
    errors: list[str] = []
    if not plan_content or not log_content:
        return errors

    if is_seed_neutral_state(plan_content, log_content):
        return errors

    plan_status_raw = get_status(plan_content, "**Estado:**")
    log_status_raw = get_status(log_content, "**Estado:**")
    plan_clean, _ = extract_status_emoji(plan_status_raw)
    log_clean, _ = extract_status_emoji(log_status_raw)

    # Plan APPROVED pero log COMPLETED
    if "APPROVED" in plan_clean and "COMPLETED" in log_clean:
        errors.append(
            "DRIFT: plan=APPROVED pero log=COMPLETED -- "
            "el log pertenece a un ciclo anterior. Limpia execution_log.md."
        )

    # Plan COMPLETED pero log IN_PROGRESS
    if "COMPLETED" in plan_clean and "IN_PROGRESS" in log_clean:
        errors.append(
            "DRIFT: plan=COMPLETED pero log=IN_PROGRESS -- "
            "el Builder no cerro su bitacora correctamente."
        )

    # Plan IN_PLANNING con log READY_FOR_REVIEW
    if "IN_PLANNING" in plan_clean and "READY_FOR_REVIEW" in log_clean:
        errors.append(
            "DRIFT: plan=IN_PLANNING pero log=READY_FOR_REVIEW -- "
            "estado imposible. El plan debe estar APPROVED antes de que el Builder entregue."
        )

    # Plan N/A pero log activo
    if ("N/A" in plan_clean or not plan_clean) and log_clean not in (
        "N/A",
        "COMPLETED",
        "PENDING",
        "",
    ):
        errors.append(
            f"DRIFT: no hay plan activo pero log={log_clean} -- "
            "limpia execution_log.md o crea un nuevo work_plan.md."
        )

    return errors
