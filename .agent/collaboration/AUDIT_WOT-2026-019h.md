# AUDIT - WOT-2026-019h

## TP Check

- TP-01: Premisa verificada en codigo real (_resolve_extra_root l.108-143 solo
  verifica .exists(), sin marker; resolve_repo_root l.37-43 SI usa .claude)
- TP-02: Fix mecanico claro: anadir check `(candidate / ".claude").exists() or
  (candidate / ".git").exists()` antes de retornar el candidate
- TP-03: Tests de regresion: AGENT_PROJECT_ROOT=<dir sin marker> -> None;
  AGENT_PROJECT_ROOT=<dir con .git> -> aceptado
- TP-04: Mutation-verify: revertir el check de marker -> dir sin marker aceptado
- TP-05: No romper los 6 tests de 019a (destino_root tiene .claude)
