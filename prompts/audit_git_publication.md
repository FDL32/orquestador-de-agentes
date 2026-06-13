# Prompt: Auditoria Git de Publicacion

contract_id: cid-audit-git-publication-v1
Skill canonica: skills/audit-git-publication/SKILL.md

## Objetivo

Auditar si un `repo_destino` esta listo para publicarse en Git sin exponer
secretos, estado privado, rutas personales, artefactos de orquestacion o deuda
sin decision. La auditoria es **dry-run only**: no ejecuta `git add`, `git rm`,
`git commit`, `git push`, ni modifica `.gitignore`.

Hereda `prompts/audit_agent_output.md`: evidencia antes que relato, CEM v0,
doble pasada adversarial y barrera verificada.

## Herramienta determinista

Ejecuta:

```powershell
python <MOTOR_ROOT>/scripts/classify_publication.py --repo-root <REPO_DESTINO> --out <REPO_DESTINO>/orchestrator_pipeline/reports/publication_manifest.json
```

No uses `--no-history` para una primera publicacion. La historia Git debe
escanearse: un secreto eliminado del working tree sigue siendo secreto en
commits previos.
`--quick` y `--no-history` saltan historia y son modo de intervencion humana:
no pueden emitir `LISTO_PARA_PUBLICAR`.
El scan completo de historia puede ser lento en repos grandes; usar `--quick`
solo para una primera orientacion, no como gate de publicacion.
Si el root contiene `MANIFEST.distribute`, el script marca `is_motor_root=true`
y bloquea por defecto con `MOTOR_ROOT_PUBLICATION_GUARD`. Solo auditorias
explicitas del motor pueden usar `--allow-motor-root`.
La ruta `--out` se excluye dinamicamente del manifest para evitar que el reporte
se auto-clasifique como untracked/publicable.

Trata `publication_manifest.json` como `[RELATO]` inicial, no como evidencia
final. La Pasada B debe abrir y re-derivar por contenido los archivos marcados
como `PUBLISH`, `PUBLISH_WITH_REDACTIONS` y `DECIDE`.

## Clasificaciones

- `PUBLISH`: candidato publicable tras verificacion manual.
- `PUBLISH_WITH_REDACTIONS`: publicable solo tras limpiar rutas locales, emails,
  hostnames internos, nombres sensibles u otra PII. Las redacciones son
  obligatorias antes de cualquier push. El JSON incluye `redaction_targets`
  acotados por archivo; si se truncan, revision manual obligatoria.
- `EXCLUDE_UNTRACKED`: no publicar; `.gitignore.proposed` puede bastar.
- `EXCLUDE_TRACKED`: no publicar y ya esta trackeado; `.gitignore` NO basta.
  Proponer `git rm --cached <path>` como accion humana, nunca ejecutarla.
- `DECIDE`: requiere decision humana. Si no esta vacio, no puede emitirse
  `LISTO_PARA_PUBLICAR`.
- `BLOQUEADO_POR_SECRETO`: secreto en tree o historia. Bloquea siempre.

`orchestrator_pipeline/**` es `EXCLUDE` por diseno: los informes de auditoria no
se publican a si mismos.
Los paths allowlisteados como `.env.example` se tratan como plantillas
publicables, pero siguen pasando patrones criticos (`AKIA`, PEM, JWT, `sk-*` y
sentinela fake). No deben bloquear por placeholders genericos.

## Pasada A: Verificacion

1. Confirmar topologia: `repo_destino`, `MOTOR_ROOT`, `AGENT_PROJECT_ROOT`.
2. Ejecutar `classify_publication.py` en modo dry-run con historia activa.
3. Registrar `tree_secret_scan.ok` y `history_secret_scan.ok` por separado.
4. Verificar que `EXCLUDE_TRACKED` y `EXCLUDE_UNTRACKED` no se mezclan.
5. Confirmar que `DECIDE` pendiente bloquea `LISTO_PARA_PUBLICAR`.
6. Confirmar que el script no modifico git status salvo el propio reporte si se
   escribio bajo `orchestrator_pipeline/reports/`.
7. Confirmar que `dirty_during_scan=false`; si cambia el arbol durante el scan,
   el veredicto no puede ser publicable.
8. Confirmar que `head_before == head_after`; si HEAD cambia durante el scan,
   el veredicto no puede ser publicable.
9. Confirmar `is_motor_root=false` salvo que la auditoria sea explicitamente
   sobre el motor y se haya usado `--allow-motor-root`.

## Pasada B: Refutacion

No aceptes el JSON del script como hecho. Re-deriva:

- Abrir cada archivo `PUBLISH` y buscar secretos, rutas absolutas personales
  (`C:\Users\...`, `/home/...`), emails, hostnames `.local`, nombres sensibles
  o contexto privado.
- Abrir cada `PUBLISH_WITH_REDACTIONS` y verificar que el riesgo existe.
- Revisar cada `DECIDE` y explicar que decision falta.
- Verificar que cualquier secreto historico produce `BLOQUEADO_POR_SECRETO`.
- Verificar que `EXCLUDE_TRACKED` no se presenta como solucionable solo con
  `.gitignore`.

## Veredictos

- `LISTO_PARA_PUBLICAR`: sin secretos en tree/historia, `DECIDE` vacio, sin
  `EXCLUDE_TRACKED` sin plan humano, y Pasada B sin blockers.
- `LISTO_CON_REDACTIONS`: solo quedan `PUBLISH_WITH_REDACTIONS` con cambios
  concretos y acotados. No es verde de publicacion; requiere redaccion previa.
- `DECIDE_PENDING`: cualquier `DECIDE` pendiente.
- `BLOQUEADO_POR_SECRETO`: secreto detectado en tree o historia.
- `NO_ACEPTAR_TODAVIA`: contradicciones, scope desconocido o evidencia ausente.

Condiciones que fuerzan `NO_ACEPTAR_TODAVIA`:

- `DIRTY_DURING_SCAN`: el arbol cambio durante el scan.
- `HEAD_CHANGED_DURING_SCAN`: HEAD cambio durante el scan.
- `HISTORY_SCAN_SKIPPED`: se uso `--quick` o `--no-history`.
- `MOTOR_ROOT_PUBLICATION_GUARD`: se esta auditando el `repo_motor` sin permiso
  explicito.

Exit codes:

- `0`: solo `LISTO_PARA_PUBLICAR`.
- `1`: `BLOQUEADO_POR_SECRETO`.
- `2`: error real de herramienta o excepcion no controlada.
- `3`: intervencion humana (`DECIDE_PENDING`, `LISTO_CON_REDACTIONS`,
  `NO_ACEPTAR_TODAVIA`, quick mode o dirty durante scan).

## Salida minima

Emitir informe en Markdown y JSON en `orchestrator_pipeline/reports/`:

```json
{
  "verdict": "LISTO_PARA_PUBLICAR|LISTO_CON_REDACTIONS|DECIDE_PENDING|BLOQUEADO_POR_SECRETO|NO_ACEPTAR_TODAVIA",
  "repo_destino": "<abs path>",
  "is_motor_root": false,
  "head_before": "<sha>",
  "head_after": "<sha>",
  "head_changed_during_scan": false,
  "tree_secret_scan": {"ok": true, "findings": []},
  "history_secret_scan": {"ok": true, "findings": []},
  "dirty_during_scan": false,
  "publication_manifest": {
    "PUBLISH": [],
    "PUBLISH_WITH_REDACTIONS": [],
    "EXCLUDE_UNTRACKED": [],
    "EXCLUDE_TRACKED": [],
    "DECIDE": []
  },
  "blocked_reasons": [],
  "manual_actions": [],
  "gitignore_proposed": []
}
```

## Que NO hacer

- No publicar, pushear, commitear, stagear ni borrar.
- No tratar `.gitignore` como solucion para archivos ya trackeados.
- No llamar "limpio" a un repo con historia Git contaminada.
- No aceptar la salida del script sin abrir archivos publicables.
- No publicar informes de `orchestrator_pipeline/`.
- No usar exit code `0` como "todo aceptado" salvo con `LISTO_PARA_PUBLICAR`.
