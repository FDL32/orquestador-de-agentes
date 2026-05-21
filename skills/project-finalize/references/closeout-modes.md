# Modos de cierre

## DELIVERY

Usalo cuando el proyecto o funcionalidad queda listo para entregar, pero seguira
activo.

Incluye:
- limpieza
- documentacion real de uso
- backlog explicitado
- verificacion final

## RELEASE

Usalo cuando ademas hay que publicar una version o artefacto.

Incluye todo lo de `DELIVERY`, mas:
- SemVer
- `CHANGELOG.md`
- notas de release
- validacion de compatibilidad
- SBOM / provenance si aplica

## HANDOFF

Usalo cuando el proyecto pasa a otra persona o equipo.

Prioriza:
- onboarding rapido
- runbook operativo
- ownership y soporte
- limitaciones conocidas
- pasos de rollback o recuperacion

## ARCHIVE

Usalo cuando el proyecto deja de mantenerse o pasa a modo historico.

Incluye:
- estado `archived` o `maintenance-only`
- nota visible en README o PROJECT
- backlog congelado o traspasado
- decision explicita sobre issues, PRs y repo read-only
