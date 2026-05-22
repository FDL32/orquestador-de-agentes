# State - WP-2026-129

Plan Activo: WP-2026-129
Estado actual: IN_PROGRESS
Rol activo: BUILDER

Resumen:
WP-2026-129 elimina el redirect legacy de `HOME`, `USERPROFILE` y `CODEX_HOME` hacia `.codex` para que OpenCode herede un entorno de review normal y no falle al arrancar.

Notas:
- El ciclo canonico arranca para Builder con el fix del entorno de review.
- `WP-2026-128` queda como closeout historico del endurecimiento del contrato de skills.
- La validacion final debe confirmar review bridge, prompt y tests alineados con la herencia normal del entorno.
