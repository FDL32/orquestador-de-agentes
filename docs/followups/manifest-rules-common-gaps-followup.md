# Follow-up: `sustainable_engineering.md` ausente de `MANIFEST.distribute`

## Metadata propuesta
- **ID sugerido:** siguiente `WOT-2026-NNN` libre.
- **deliverable_type:** documentation (solo añadir entrada a MANIFEST).
- **delivery_authority:** repo_motor
- **Prioridad:** Baja (no bloquea P6, hallazgo menor).

## Objetivo

Anadir `.agent/rules/common/sustainable_engineering.md` a `MANIFEST.distribute` para que
sea distribuido correctamente a los destinos durante la instalacion del motor.

## Antecedentes

El contrato P6 (Seccion 5.4.1, hallazgo 3) descubrio que `sustainable_engineering.md`
vive en `.agent/rules/common/` (mismo bolsillo que los otros 5 modulos ya enlistados)
pero NO esta enlistado en `MANIFEST.distribute`.

`check_distribution_boundary.py` no muerde porque solo aplica en la direccion
entrada->fichero real, no al reves. Por tanto, el fichero existe pero no se distribuye
automaticamente.

## Contrato del fix (minimo)
- Añadir `.agent/rules/common/sustainable_engineering.md` tras
  `.agent/rules/common/manifest_contracts.md` en `MANIFEST.distribute` (mismo patron
  que los otros 5 modulos de `rules/common`).
- Verificar con `python scripts/install_agent_system.py --sync --dry-run` que el
  fichero aparece en los archivos a copiar al destino.

## Non-goals
- No mover `sustainable_engineering.md` de lugar.
- No revisar los otros modulos de `rules/common` (otro trabajo).

## Criterio binario de cierre
- [ ] `.agent/rules/common/sustainable_engineering.md` enlistado en `MANIFEST.distribute`.
- [ ] `--sync --dry-run` lo incluye en el listado.
