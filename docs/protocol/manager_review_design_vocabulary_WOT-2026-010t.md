# Manager review: vocabulario de diseno profundo (WOT-2026-010t)

> Origen externo: `mattpocock/skills@dcfc232` (`skills/engineering/codebase-design`),
> MIT, **Adapted** (no se copio texto largo ni codigo). Fila en `CREDITS.md`.
> Este protocolo da al Manager lenguaje preciso para DESCRIBIR el diff, no para
> exigir arquitectura nueva. Checklist accionable: ver
> `skills/man-review-implementation/references/review-checklist.md`. Anti-patron:
> AP-16 en `skills/_shared/anti-patterns.md`.

## Glosario operativo (uso en review)

- **Module:** cualquier cosa con interfaz e implementacion (funcion, clase,
  paquete, slice). Escala-agnostico.
- **Interface:** TODO lo que un caller debe saber para usar el module bien:
  firma + invariantes + orden + modos de error + config requerida. No solo el tipo.
- **Implementation:** el cuerpo interno del module.
- **Depth:** leverage en la interfaz: cuanto comportamiento ejercita un caller
  por unidad de interfaz que debe aprender. **Deep** = mucha implementacion tras
  interfaz pequena. **Shallow** = interfaz casi tan compleja como la implementacion.
- **Seam (Feathers):** lugar donde alteras comportamiento sin editar ahi. Donde
  poner el seam es decision propia, distinta de que va detras.
- **Adapter:** algo concreto que satisface una interfaz en un seam. Describe rol
  (que slot llena), no sustancia.
- **Deletion test:** imagina borrar el module. Si la complejidad desaparece, era
  pass-through. Si reaparece en N callers, ganaba su sitio.
- **Interface is the test surface:** callers y tests cruzan el mismo seam. Si
  necesitas probar POR DETRAS de la interfaz, el module tiene la forma equivocada.

## Principios de uso (anti-over-engineering)

1. **Describir, no exigir.** El vocabulario nombra lo que el diff YA tiene. NO se
   usa para pedir interfaces/seams nuevos "para que sea limpio".
2. **Un adapter = seam hipotetico; dos = seam real.** No introduzcas un seam si
   nada varia a traves de el (AP-16).
3. **Deletion test antes de aceptar/pedir una abstraccion.** Si borrarla no
   reaparece complejidad, no se anade.
4. **`interface is the test surface` NO significa "mas mocks".** Significa
   preguntar que contrato observable se prueba.

## Ejemplo real aplicado: `.agent/scope_gate.py` (WOT-2026-009b)

Artefacto existente del motor, NO inventado. Estado verificado el 2026-06-18.

Interfaz publica (lo que los callers cruzan):

- `parse_flt_namespaced(work_plan_content, *, motor_root, project_root, delivery_authority="repo_motor") -> dict[str, set[str]]`
- `parse_forbidden_surfaces(work_plan_content, *, project_root) -> set[str]`
- `parse_files_likely_touched(...)`
- `get_changed_files(*, project_root, motor_root, run_fn=subprocess.run) -> set[str] | None`

Implementacion interna (lo que los callers NO ven):

- `_extract_section_paths(lines, heading, project_root)` (privado): extrae rutas
  de cualquier seccion markdown por heading y aplica heuristica de token-de-ruta.

### Lectura con el vocabulario

| Termino | Lectura en scope_gate.py |
|---|---|
| **module** | `scope_gate.py` como slice de parsing FLT/Forbidden + diff. |
| **interface** | Las 4 funciones publicas. Un caller (`pre_handoff_guard`) solo necesita conocer esas firmas; no necesita saber como se extraen las rutas. |
| **depth** | **Deep.** Mucha logica (heuristica de token, namespacing por delivery_authority, parsing porcelain `-z` de git) tras una interfaz pequena. |
| **seam interno** | `_extract_section_paths` es un seam INTERNO: `parse_flt_namespaced` y `parse_forbidden_surfaces` alteran su comportamiento pasando distinto `heading`, sin duplicar la logica de extraccion. |
| **seam externo** | `get_changed_files(run_fn=...)`: el parametro `run_fn` ES un seam real -- los tests inyectan un `run_fn` fake (segundo "adapter") sin tocar git de verdad. Dos implementadores (subprocess real + fake de test) => seam justificado, NO inventado. |
| **adapter** | El `run_fn` fake de los tests es un adapter que satisface el seam de `get_changed_files`. |
| **deletion test** | Si borraras `_extract_section_paths` e inlinearas su logica en cada `parse_*`, reaparece complejidad duplicada en >=3 callers. Gana su sitio: NO es pass-through. |
| **interface is the test surface** | Los tests de `get_changed_files` cruzan la misma interfaz que `pre_handoff_guard` (la funcion publica + `run_fn`), no van por detras. Forma correcta. |

### Que NO haria el Manager con este ejemplo

- NO exigir que `_extract_section_paths` se convierta en una clase `PathExtractor`
  con interfaz formal: el `run_fn` ya prueba que el unico seam que varia es el de
  git. Pedir mas seams seria AP-16.
- NO pedir un segundo adapter para `parse_forbidden_surfaces` "por simetria": no
  hay nada que varie a traves de el; un solo uso = seam hipotetico, no real.

## Relacion con `diagnosing-bugs` vs `systematic-debugging`

`mattpocock/skills` renombro `diagnose` -> `diagnosing-bugs` (loop de diagnostico
de bugs). Contraste con nuestra skill local `skills/systematic-debugging/SKILL.md`:

- **Lo que se puede adoptar (lenguaje):** la idea de nombrar la causa raiz antes
  de parchear, y de tratar el diagnostico como un loop con hipotesis explicitas.
- **Lo que NO se cambia (barrera de seguridad del motor):** el **limite de 3
  intentos** de `systematic-debugging/SKILL.md` Fase 4 (Control de Umbral) se
  CONSERVA intacto. Es una restriccion del motor que impide que un agente itere
  indefinidamente sobre un problema mal entendido. `diagnosing-bugs` enriquece el
  vocabulario de causa raiz, pero NO reemplaza esa skill ni relaja su umbral.

Conclusion: `diagnosing-bugs` se trata como guia de pensamiento (Adapted, no
ported); el limite de 3 intentos permanece como contrato local no negociable.
