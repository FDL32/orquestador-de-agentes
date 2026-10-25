# Archivado de colaboracion (WP-2026-100)

- `scripts/archive_collaboration_artifacts.py` mueve `PLAN_WP-*.md` y
  `AUDIT_WP-*.md` cerrados a `.agent/collaboration/_archive/plan_audit/`.
- El ticket activo conserva solo sus documentos vivos en `collaboration/`.
- El archivador es idempotente: segunda ejecucion = no-op.
- Usa `--dry-run` para previsualizar sin modificar, `--list-active` para ver
  archivos activos.

Relacionado: superficies vivas NO archivables en
`collaboration_live_surfaces.md` (WP-2026-107); regla de herencia al absorber
fichas del backlog en `backlog_fusion_herencia.md` (WOT-2026-042l).
