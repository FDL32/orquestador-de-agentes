"""
Goose native skill integration for refactor-manager.

Allows Goose to invoke RefactorManager directly without subprocess overhead.
Handles skill invocation, phase management, and artifact collection.
"""

import json

from agent_system.refactor_kit import RefactorManager


def invoke(target: str, agent: str = "goose", work_dir: str = ".refactor") -> dict:
    """
    Invoke refactor-manager as native Goose skill.

    Manager approval gates are built into RefactorManager.run(),
    so they will prompt Manager during execution.

    Args:
        target: File or module to refactor (required)
        agent: AI agent (goose, claw, manual) - default: goose
        work_dir: Directory for refactoring artifacts - default: .refactor

    Returns:
        dict with keys:
        - status: "COMPLETED" | "FAILED"
        - target: The file refactored
        - phases: List of phase names executed (["01_analysis", "02_plan", ...])
        - artifacts: dict with results from each phase
        - error: (if status == "FAILED") Error message

    Example:
        >>> result = invoke(target="src/core.py")
        >>> print(result["status"])
        'COMPLETED'
        >>> print(result["phases"])
        ['01_analysis', '02_plan', '03_refactor', '04_validation', '05_iteration']
        >>> analysis = result["artifacts"]["01_analysis"]
    """
    try:
        # Create RefactorManager instance
        manager = RefactorManager(target=target, agent=agent, work_dir=work_dir)

        # Execute 5-phase workflow (Manager approval gates built in)
        manager.run()

        # Collect results from all 5 phases
        artifacts = {}
        phase_names = [
            "01_analysis",
            "02_plan",
            "03_refactor",
            "04_validation",
            "05_iteration",
        ]

        for phase in phase_names:
            phase_file = manager.phases_dir / f"{phase}.json"
            if phase_file.exists():
                artifacts[phase] = json.loads(phase_file.read_text(encoding="utf-8"))

        # Return success result
        return {
            "status": "COMPLETED",
            "target": target,
            "phases": list(artifacts.keys()),
            "artifacts": artifacts,
        }

    except Exception as e:
        # Return error result
        return {"status": "FAILED", "target": target, "error": str(e)}
