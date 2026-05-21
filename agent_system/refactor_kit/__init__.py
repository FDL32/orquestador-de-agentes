"""
Refactor Kit: Portable code refactoring for any Python project.

This package provides a 5-phase protocol to refactor Python code safely,
minimizing regression risks by separating analysis, planning, and execution.

Usage:
    from refactor_kit import RefactorManager
    manager = RefactorManager(target="src/core.py")
    manager.run()
"""

from .refactor_manager import RefactorManager


__all__ = ["RefactorManager"]
