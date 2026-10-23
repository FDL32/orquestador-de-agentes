# Propuesta: centralizar el criterio de escalada NORMA -> barrera (2026-10-23)

> Cierra el hueco senalado por el usuario tras aplicar el eje G: `decision_capsule_schema.md`
> declara el umbral "2+ casos medidos de deriva antes de escalar a guard" como si viniera de
> `doc_optimization.md`. Es una atribucion FALSA (verificada en esta misma pasada: `grep -n
> "2+\|dos casos\|casos medidos" .agent/rules/common/cem_v0_evidencia_forense.md AGENTS.md
> prompts/doc_optimization.md` -> cero coincidencias). El umbral no tenia fuente canonica: se
> acuno ad-hoc esta sesion y quedo flotando en un solo fichero, listo para que una futura G2/G3
> lo reescriba con otras palabras y diverja.

## Error encontrado en esta pasada (antes del bucle)

**La cita "mismo umbral que usa `doc_optimization.md` para otras barreras" es imprecisa.**
Verificado leyendo `doc_optimization.md` PASO 5 completo: ese paso gobierna deuda-vs-tope-duro
para EXCESO DE TAMANO de fichero (bytes/caracteres sobre un gate), un eje distinto al de
"cuantos casos de deriva semantica justifican construir un guard para una capsula NORMA". Nunca
declara un numero "2+". La cifra que `decision_capsule_schema.md` cita como prestada en
realidad no existe en ningun otro fichero -- es la PRIMERA vez que se declara, y el fichero que
la usa no es el que deberia fijarla (el fichero de G1, no un modulo CEM transversal).

## Segundo error encontrado en esta pasada (autocorreccion antes del bucle)

El borrador original de esta misma propuesta afirmaba que los 3 focos de "NORMA, no barrera"
usaban "redaccion ligeramente distinta cada vez" del umbral de escalada -- falso, verificado:
`audit_autonomous_ticket_batch.md:514` declara el ESTATUS sin ningun criterio numerico de
escalada. Corregido abajo para no repetir, en la propuesta que corrige una atribucion
inventada, el mismo vicio de citar una fuente sin verificarla letra por letra.

## Diagnostico

**Correccion sobre el alcance real (verificado con `grep -n "casos\|2+\|escal"
prompts/audit_autonomous_ticket_batch.md`, cero coincidencias):** la declaracion "NORMA, no
barrera" SI aparece en al menos 3 lugares de este repo (`decision_capsule_schema.md`,
`prompts/audit_autonomous_ticket_batch.md:514`, y el eje D de `skill_trigger_governance.md`
implicitamente al no tener verificador de prosa), pero SOLO `decision_capsule_schema.md`
intenta fijar un umbral numerico de escalada -- los otros dos declaran el estatus sin ningun
criterio de "cuando pasar a guard". Eso es el mismo sintoma desde el otro lado: no por
redeclaracion divergente (todavia), sino por AUSENCIA de un criterio compartido al que apuntar.
El riesgo es el mismo que nombra `.agent/rules/common/x09_skill_prompt_governance.md` (X-09,
"skill apunta, prompt gobierna") para skill<->prompt: sin un ancla unica, cada NORMA nueva
inventa su propio criterio (o no inventa ninguno), y dos cápsulas futuras pueden terminar con
umbrales distintos sin que nadie lo note (`[G#]` solo valida sintaxis, nunca semantica -- no
hay guard que detecte la divergencia).

## Propuesta: fijar el criterio UNA vez en el eje F (CEM v0), G1 lo cita

**Por que el eje F y no uno nuevo:** el criterio es CEM v0 puro (gobierna como se decide entre
NORMA y barrera para CUALQUIER regla del sistema, no solo para cápsulas G) -- mismo dominio que
F1-F7 (`cem_v0_evidencia_forense.md`). Anadir una letra nueva mezclaria de nuevo dos alcances
(ya se evito ese error al NO meter G en D); el criterio de escalada no es especifico del eje G,
asi que vive en F, no en G.

**Por que SIN bullet nuevo en `AGENTS.md`:** los F1-F7 existentes tienen todos un bullet
reflejo en la seccion CEM v0 de `AGENTS.md` (la "cuspide" siempre-cargada) con su cita `[F#]`.
Un F8 con bullet nuevo anadiria bytes a un fichero que YA esta 4116 B sobre el gate Codex. Este
criterio NO necesita estar siempre-cargado: solo es relevante para quien AUTORA una capsula de
decision nueva (evento raro, no una sesion cualquiera) -- calza con la clase
`referencia-bajo-demanda` de `doc_optimization.md` PASO 1, no con `siempre-cargado`. Se declara
F8 SOLO en `cem_v0_evidencia_forense.md`, sin espejo en `AGENTS.md`. `check_reference_keys.py`
ya soporta esto: `discover_citation_files()` escanea `AGENTS.md` Y `.agent/rules/common/*.md`,
asi que una cita `[F8]` puesta DENTRO de `decision_capsule_schema.md` (que vive en
`.agent/rules/common/`) resuelve sin necesidad de que `AGENTS.md` la mencione.

### Tercer error encontrado -- bucle adversarial (codex, 2026-10-23, BLOQUEANTE confirmado)

**Hallazgo verificado de forma independiente** (`grep -rln "NORMA, no barrera" --include="*.md"
.`): el borrador original de este F8 universalizaba "2+ casos medidos" como criterio para
"cualquier regla NORMA del sistema". Falso por evidencia: existen **13 ficheros** con la
declaracion "NORMA, no barrera" en este repo (no 2, ni 3) --
`.agent/rules/common/sustainable_engineering.md`, `CONSTITUTION.md`, `prompts/ensemble_loop.md`,
`prompts/_shared/topology_artifact_locations.md`, `prompts/orchestrator_session_close_full_audit.md`,
`prompts/builder_invocation_contract.md`, `prompts/escalate_to_motor.md`, ademas de
`decision_capsule_schema.md` y `audit_autonomous_ticket_batch.md` ya censados -- y **NINGUNO de
los 10+ restantes usa un umbral por conteo de casos**: todos usan "deuda declarada con
dueno/ticket" (el patron de `doc_optimization.md` PASO 5, ese si real). Imponer "2+ casos" como
EL criterio universal del repo seria la MISMA atribucion inventada que este item nace
corrigiendo, aplicada 10 veces en vez de 1. **Fix: F8 se acota EXPLICITAMENTE al eje G** (no se
universaliza); el resto de declaraciones NORMA siguen su propio criterio de dueno/ticket sin
tomar prestado este numero.

### Contenido nuevo: `F8` en `.agent/rules/common/cem_v0_evidencia_forense.md`

```markdown
<a id="f8"></a>
**F8.** **Criterio de escalada NORMA -> barrera para capsulas del eje G (alcance ACOTADO, no
universal):** una capsula del eje G (`.agent/rules/common/decision_capsule_schema.md`,
documentada como NORMA) escala a guard cableado SOLO tras 2+ casos MEDIDOS de deriva real en
ESA capsula -- nunca preventivamente, ni por volumen hipotetico. Futuras capsulas G (G2, G3...)
CITAN este item en vez de reescribir su propio numero: redeclararlo por capsula es el mismo
anti-patron que X-09 ya nombra para skill<->prompt
(`.agent/rules/common/x09_skill_prompt_governance.md`). **Alcance DECLARADO Y LIMITADO:** este
umbral NO gobierna las demas declaraciones "NORMA, no barrera" del repo (censo 2026-10-23: 13
ficheros, ninguno de los otros 10+ usa conteo de casos -- todos usan deuda con dueno/ticket);
universalizarlo fuera del eje G repetiria la atribucion inventada que este item corrige en
origen. Origen (2026-10-23): `decision_capsule_schema.md::G1` declaro este umbral
atribuyendolo a `doc_optimization.md` -- verificado, `doc_optimization.md` no declara ningun
umbral numerico de escalada (su PASO 5 gobierna deuda-vs-tope-duro de TAMANO de fichero, un eje
distinto). Este item ES el origen canonico del numero para el eje G: citar `[F8]` es citar la
fuente real, no una atribucion inventada.
```

### Cambio en `decision_capsule_schema.md`

Texto actual (parrafo ESTATUS DECLARADO):

    Justificacion por VOLUMEN (1 sola instancia hoy, G1) y por el mismo umbral que usa
    `doc_optimization.md` para otras barreras (2+ casos medidos de deriva antes de escalar a
    guard mecanico) -- no por el eje D como precedente...

Texto nuevo:

    Justificacion por VOLUMEN (1 sola instancia hoy, G1) y por el criterio de escalada
    canonico [F8] -- no por el eje D como precedente...

Y en el bloque de "Riesgo residual declarado" de G1, sustituir "mismo patron de 'norma, no
barrera' declarado arriba" por "mismo criterio [F8] declarado arriba" (misma cita, sin
reescribir el numero una segunda vez dentro del mismo fichero).

**Coste:** 0 B en `AGENTS.md`. `decision_capsule_schema.md` queda mas corto (sustituye ~140
caracteres de justificacion propia por una cita de 5 caracteres `[F8]`), `cem_v0_evidencia_forense.md`
crece ~950 B (fichero `referencia-bajo-demanda`, no cuenta para ningun gate).

## Verificacion

1. `check_reference_keys.py` -- debe resolver `[F8]` contra `**F8.**` en
   `cem_v0_evidencia_forense.md`, y la cita `[F8]` dentro de `decision_capsule_schema.md` (otro
   fichero del mismo directorio `.agent/rules/common/`, ya dentro de la cobertura del guard).
2. `check_distribution_boundary.py` -- ningun fichero nuevo, no hay entrada de manifiesto que
   anadir (ambos ficheros ya estan en `MANIFEST.distribute`).
3. `build_llms.py --check` -- `llms-full.txt` no cambia (ninguno de los dos ficheros tocados
   esta en `INLINE_IN_FULL`, igual que E/F/T/cem hoy).
4. `scripts/check_encoding_guard.py` sobre los dos ficheros editados (`cem_v0_evidencia_forense.md`,
   `decision_capsule_schema.md`) -- gap verificado por codex en el bucle: faltaba en el plan
   original, igual que en la verificacion del eje G de esta misma sesion.
5. Re-medir gates de `AGENTS.md` -- deben quedar IDENTICOS a los actuales (0 B de cambio en ese
   fichero): codex deficit=4116, claude deficit=0.

## Non-goals

- NO reescribe los otros dos focos de "NORMA, no barrera" detectados en el grep
  (`builder_invocation_contract.md`, `audit_autonomous_ticket_batch.md`) -- eso es una migracion
  aparte, de mayor alcance, que no es parte de cerrar el hueco declarado sobre el eje G. Se
  declara como candidato futuro, no se ejecuta aqui.
- NO construye un guard que verifique que las capsulas NORMA citan `[F8]` en vez de redeclararlo
  -- mismo criterio de rigor proporcional que el propio F8 declara (NORMA hasta 2+ casos de
  deriva medida; hoy serian 0 casos de divergencia real, solo 1 caso de atribucion incorrecta
  ya corregido en el nacimiento).

## RONDA 1 -- bucle adversarial (2026-10-23)

4 lentes despachadas (codex, deepseek, mistral, cohere). codex: CHANGES con 1 BLOQUEANTE real
(universalizar "2+ casos" a las 13 declaraciones "NORMA, no barrera" del repo cuando solo 1
-- esta propuesta -- usaba ese criterio; las otras 10+ usan deuda con dueno/ticket), verificado
por mi de forma independiente con `grep -rln`. CORREGIDO: F8 se acoto EXPLICITAMENTE al eje G,
sin universalizar. mistral y cohere: APPROVE (no corrieron el grep de censo ellos mismos, menor
rigor). deepseek no llego a tiempo de esta pasada.

**Aplicado:** `F8` anadido a `cem_v0_evidencia_forense.md` (acotado al eje G),
`decision_capsule_schema.md` edita 2 frases para citar `[F8]` en vez de reescribir el criterio.
Verificado: `check_encoding_guard.py` OK, `check_reference_keys.py` OK,
`check_distribution_boundary.py` OK, `build_llms.py --check` OK (sin cambios, ninguno de los
dos ficheros esta en `INLINE_IN_FULL`), gates de `AGENTS.md` identicos (codex deficit=4116,
claude deficit=0, 0 B de cambio).

**Estado: APLICADO.**
