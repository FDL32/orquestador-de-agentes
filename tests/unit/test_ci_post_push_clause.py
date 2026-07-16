"""WOT-2026-023c contract: the motor's pipeline/audit prompts must carry the
CI-remote-post-push barrier.

Brecha verificada: ninguna auditoria del motor exigia comprobar el CI REMOTO
tras el push, asi que una cadena podia cerrarse "verde" y publicar con el CI en
ROJO (incidente 2026-07-12: suite local 4022 passed, el CI ubuntu fallo con 2
tests, ningun gate lo vio). El pipeline CODE-ONLY -- el que se usa -- no
mencionaba el CI en absoluto.

DoD (binario): los 4 prompts contienen la clausula de CI post-push.
Mutation: quitar la clausula (el estado declarado PUBLICADO_CON_CI_PENDIENTE)
de uno -> su caso parametrizado CAE.
"""

from __future__ import annotations

from pathlib import Path

import pytest


PROMPTS = Path(__file__).resolve().parents[2] / "prompts"

# The 4 prompts the ticket enumerates (orchestrator + the 3 audit prompts).
CI_CLAUSE_PROMPTS = [
    "orchestrator_pipeline_codeonly.md",
    "audit_pipeline_codeonly.md",
    "audit_pipeline.md",
    "audit_autonomous_ticket_batch.md",
]

# Declared state (not a silence) that the clause introduces. Distinctive enough
# to be a stable teeth marker: it appears nowhere else.
DECLARED_STATE = "PUBLICADO_CON_CI_PENDIENTE"


@pytest.mark.parametrize("rel", CI_CLAUSE_PROMPTS)
def test_prompt_declares_ci_post_push_barrier(rel: str) -> None:
    text = (PROMPTS / rel).read_text(encoding="utf-8")
    assert DECLARED_STATE in text, (
        f"{rel} debe declarar la barrera de CI remoto post-push"
        f" (WOT-2026-023c): falta el estado declarado {DECLARED_STATE!r}."
        " Una suite local verde NO es evidencia de portabilidad."
    )


@pytest.mark.parametrize("rel", CI_CLAUSE_PROMPTS)
def test_ci_clause_cites_gh_run_with_real_returncode(rel: str) -> None:
    """The detective side must read the REAL returncode, never `$?` after a
    pipe (fundacional pitfall). The clause names `gh run` and forbids `$?`."""
    text = (PROMPTS / rel).read_text(encoding="utf-8")
    assert "gh run" in text, (
        f"{rel}: la cara detectiva debe verificar el CI con gh run list/watch"
    )
    # It must name reading the real returncode, not $? after a pipe.
    assert "PIPESTATUS" in text or "returncode" in text, (
        f"{rel}: la clausula debe leer el RETURNCODE REAL, no `$?` tras pipe"
    )
