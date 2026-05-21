# Checklist de cierre profesional

## Minimo viable

- Tests, lint y checks relevantes en verde
- Sin logs, prints, scripts temporales ni archivos basura conocidos
- README alineado con instalacion, uso y estructura real
- `PROJECT.md`, `CLAUDE.md` y docs de agentes sincronizados si existen
- `CHANGELOG.md` o notas de entrega actualizadas
- Limitaciones y pendientes visibles; no TODOs ocultos
- Sin secrets, rutas personales o credenciales de ejemplo peligrosas

## Recomendado

- `LICENSE` claro para repos compartidos o publicos
- `SECURITY.md` con forma de reportar vulnerabilidades
- `CONTRIBUTING.md` si esperas colaboracion externa o interna amplia
- `CODEOWNERS` o ownership equivalente para revisiones y mantenimiento
- Lockfiles y manifests coherentes
- Smoke test en entorno limpio
- Estado de mantenimiento y soporte explicitados

## Avanzado

- SBOM para software distribuible
- Artifact attestation / provenance para builds publicadas
- `CITATION.cff` si el software debe citarse
- Reglas de branch protection / status checks definidas
- Politica de archivado o fin de vida si el proyecto se congela
