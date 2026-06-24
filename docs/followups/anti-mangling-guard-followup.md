# Follow-up: barrera anti-mangling en el encoding guard

> Draft de seguimiento (no es un ticket activo). Origen: incidente CTL-2026-007a.
> Materializado en ruta versionable del motor para que el Manager pueda
> convertirlo en `work_plan` cuando proceda. NO bootstrapped en el bus.

## Metadata propuesta
- **ID sugerido:** siguiente `WOT-2026-NNN` libre (el motor usa prefijo `WOT-`).
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Prioridad:** Media

## Objetivo
`scripts/encoding_guard.py` debe detectar la firma de mangling que hoy pasa: un
TAB literal (0x09) o un fragmento de backtick roto (p.ej. `` `r ``) inyectado
dentro de un bullet de ruta en markdown operativo
(`- <TAB>ests/...`, `- src/pipeline/\`r`). Se considera cumplido cuando el guard
FALLA (exit 1) sobre el fixture corrupto y PASA (exit 0) sobre el limpio.

## Premisa verificada (read-only)
- `_ALLOWED_CONTROL_CHARS = {"\t", "\n", "\r"}` en `scripts/encoding_guard.py`:
  el TAB esta permitido globalmente, asi que `find_control_chars` NO marca el
  TAB-en-bullet. `VERIFICADO EN CODIGO`.
- Reproducido en CTL-2026-007a: el guard sobre el work_plan corrupto solo
  detecto un `<0x0C>` suelto, NO los `- <TAB>ests/...`. `cat -A` confirma
  `- ^Iests/...`. `VERIFICADO POR BYTES`.
- El gap es real y narrow: TAB legitimo en general (tablas markdown), pero TAB
  tras `- ` en un bullet de ruta es corrupcion.

## Files Likely Touched (repo_motor)
- `scripts/encoding_guard.py`
- `scripts/check_encoding_guard.py`
- el test del guard (p.ej. `tests/unit/test_encoding_guard.py` si existe; si no,
  el test que cubra `file_issues`/`check_encoding_guard`)

## Contrato del fix (minimo)
- Anadir un detector especifico (p.ej. `find_path_bullet_mangling(text)`) que
  marque lineas `^\s*-\s` seguidas de: (a) un TAB 0x09, o (b) un backtick sin
  cerrar / fragmento `` `<1-2 chars>$ `` que indique path truncado.
- NO relajar `_ALLOWED_CONTROL_CHARS` global: el TAB sigue valido en otros
  contextos. La deteccion es especifica de bullets de ruta en markdown operativo.
- Integrar el finding en `file_issues()` / el reporte de
  `check_encoding_guard.py`.

## Barrera de regresion (obligatoria, fail-sin-fix)
- Fixture corrupto disponible: el FLT real de 007a en
  `repo_destino/.agent/collaboration/_007a_work_plan_CORRUPTED.evidence`
  (`- \tests/unit/...` con TAB + `- src/pipeline/\`r`). Copiar a un fixture de
  test del motor para no depender del destino.
- El test debe FALLAR sin el fix (guard PASA el fixture corrupto = falso verde
  actual) y PASAR con el fix (guard exit 1 sobre corrupto, exit 0 sobre limpio).

## Non-goals
- No cambiar la convencion global de TABs ni romper tablas markdown legitimas.
- No tocar artefactos de CTL-2026-007a (ya cerrado y revertido).
- No ampliar a otras clases de mojibake no relacionadas.

## Criterio binario de cierre
- [ ] guard FALLA (exit 1) sobre fixture con `- <TAB>path` y `` - `fragmento ``.
- [ ] guard PASA (exit 0) sobre el work_plan limpio (12 FLT correctos).
- [ ] test de barrera demostrado fail-sin-fix / pass-con-fix.
- [ ] `ruff` + suite canonica del motor verdes.

## Trazabilidad
- Memoria del motor: `obs-no-heredoc-edit-frozen-contracts`,
  `obs-closeout-noncontiguous-commit-override` (`.agent/runtime/memory/observations.jsonl`).
