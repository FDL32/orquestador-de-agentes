# Estado y decisiones

- Estado: APROBADO EN PRINCIPIO por el usuario (2026-11-09). Canon: filas P30 a P33 de `.agent/rules/common/vuelo_pilares.md`; este fichero es su fuente larga versionada.
- Orden vigente del usuario (messageIds 6635ac64-d8c1-4684-9081-1258f406c801 y cf1548e2-edaf-4d98-912c-b923005f963a, web, 2026-11-19; la primera por consumo de tokens, la segunda por usar al nuevo revisor como supervisor de los IM): la celda del IM es BUILDER = codex gpt-5.6-luna (hijo de cada IM, lanzado con `delegate_task`; cuentas codex distintas entre IM, sin el modelo sol), REVISOR = opencode nan/mimo-v2.6-flash y V1 = opencode nan/deepseek-v4-flash (otro modelo que el builder y que el revisor, con acceso real a shell, revisa el diff antes de commitear). Un IM nunca se lanza como sesion unica. Niveles de estas claves en el registro v2 de `.agent/config/agents.json` (WOT-2026-221b); el prompt solo remite a esa fuente. Tension abierta registrada: `diseno/DISENO_NIVELES_MODELO_20261115.md` s.9 afirma que el V1 del canon fue sobrescrito por luna desde 2026-11-21 19:52, lo que no resuelve contra esta linea (medido en base 679649a0: V1 = deepseek); pendiente de decision del usuario. HISTORIA ya no vigente (conservada): Decision del usuario (messageId fe7a644c-0f51-491f-b7ec-e021109b0682, web): se aprueba el sistema agnostico y, por el momento, la celda del IM es: BUILDER = codex (hijo de cada IM, lanzado con `delegate_task`); IM#1 con REVISOR deepseek (nan); IM#2 con REVISOR glm 5.3 flash (nan). Un IM nunca se lanza como sesion unica.
- Orden anterior del usuario (messageId 85feaef0-d2ba-449b-a434-3f4417e08fe8, web): terminar IM-106 e IM-107 como estaban y aplicar la celda completa a los siguientes tickets.
- WOT-2026-221d actualiza la declaracion para los siguientes despachos: `celdas.im` usa builder y V1 codex gpt-5.6-luna, revisor claude-sonnet-5, nivel medio, esfuerzo alto y cuenta alvarovans preferente con brabander de refugio; `celdas.tr` conserva triador gemma4 y revisor mimo-v2.6-flash. Las rondas ya iniciadas conservan el contrato anterior.
- Orden del usuario (messageId 3a21b699-ecc7-4611-bae4-4ae7cbd5b675, web, 2026-11-09): TODO TR e IM se lanza con dos lentes sobre su entregable. Canon: fila P34 de `vuelo_pilares.md`. P30 solo describia la celda del IM; el caso TR (sesion de triaje o redaccion, p. ej. el borrador de una ficha) quedaba sin escribir y TR-29 se lanzo como sesion unica por ese hueco.
- Orden del usuario (messageId fae5e1cd-04af-4a40-bc18-1ad8f432c98f, web, 2026-11-09): las lentes del TR son TRIADOR gemma4 (nan) y REVISOR glm5.3-flash (nan); el sistema tiene en cuenta el contexto de gemma4 durante los triajes y el revisor puede lanzar varios subagentes para no colapsar su contexto. Canon: P35. Su extension a la celda del IM (messageId 0a62eaf3-b688-46a9-967f-80c745e9fa62) es P36. Pendiente medir la ventana efectiva de gemma4 (la API de nan lista el modelo sin longitud de contexto) y declararla en el registro de backends.
- Orden vigente del usuario (messageId d99b0f8a-8136-49e2-8062-f7a85f014c9d, web, 2026-11-12): la celda del TR es TRIADOR gemma4 (nan) y REVISOR mimo-v2.6-flash (nan); esta orden SUSTITUYE la asignacion de revisor de la orden de 2026-11-09 (messageId fae5e1cd-04af-4a40-bc18-1ad8f432c98f), que queda SUPERADA en esa parte; el TRIADOR no cambia. Canon: P35.
- Orden del usuario (messageId ae8a73d2-9a01-46b5-a357-e34e67c17497, web, 2026-11-12): la cadena anidada del TR (hijo redactor y nieto comprobador lanzado por el propio hijo con delegate_task) debe quedar en la documentacion canonica: protocolo y estado en la seccion Cadena anidada del TR de este fichero.
- Pendiente del usuario: U2 (criterio de cierre del piloto de la celda) y U3 (politica de familias de lentes). Pendiente de implantar: ficha de diseno y resolvedor.
- Origen: el 2026-11-09 la coordinadora lanzo IM-106 e IM-107 como sesiones unicas; la orden permanente (revisor nan mas builder codex hijo) se habia degradado en la regeneracion manual de la seccion de ordenes del ARRANQUE de cada relevo. Un bucle de 8 lentes (todas CHANGES sobre la primera propuesta) corrigio la causa: sin canon versionado, sin regla de precedencia y sin comprobacion de conformidad.
# Sistema agnostico de celdas y lentes del vuelo (cambiar de lente o de modelo editando UNA declaracion)
## 1. Lo que YA existe en el motor (medido en .agent/config/agents.json)
- ensemble_registry.backend_keys: las claves activas declaran backend, model, lab, family, tier histórico, generation y los campos v2 `nivel`, `esfuerzo`, `acceso`, `presupuesto`, `limite`, `uso_maximo` y `nivel_decidido_por`. `tier` es derivado solo para lectores históricos y no decide gates.
- ensemble_profiles (45): como se lanza cada una (backend, channel agent o api, modelo, write, backend_key).
- role_mapping (orchestrator, manager, revisor, builder, auditor, challenger) con backend/model y ensemble_profiles_ref; ensemble_registry.loop_shapes (UNI-n, DBL-n).
- La tabla única de techos es `ensemble_registry.uso_maximo_por_tipo`, un dict plano por nivel que consume T1; cada clave solo referencia el nivel con `uso_maximo`.
- Lo que NO existe: (a) el PANEL de lentes de una ronda como declaracion: vive hardcodeado en los scripts de lanzamiento que escribe cada coordinadora a mano (profiles, claves, entorno de cuenta, que bundle recibe cada una); (b) la INDEPENDENCIA por familia como regla ejecutable aunque el dato family ya esta en el registro; (c) un solo sitio donde cambiar un proveedor. La CELDA del IM como rol declarado deja de estar en esta lista con WOT-2026-221d: ahora existe la clave raiz `celdas` de `agents.json`; los tres puntos anteriores siguen sin existir.

### 1.1 Declaracion vigente de celdas (WOT-2026-221d)

`agents.json` declara `celdas.im` y `celdas.tr` fuera de
`ensemble_registry.classification`. Cada slot referencia un `backend_key` y
no duplica backend, modelo, nivel ni esfuerzo. La forma de IM es `builder`,
`revisor`, `v1`, `nivel`, `esfuerzo`, `cuenta` (`preferente=alvarovans`,
`refugio=brabander`), `fase_aplicable` y
`fase_B_subagentes_largos_claude=false`; TR declara `triador` y `revisor`.

`scripts/flight/check_cell_conformance.py` resuelve esos `backend_key` mediante
carga perezosa de `agents.json`; acepta `--agents-json` para fixtures y
mutaciones. Desde `2026-11-24T00:00:00+01:00` valida los siete datos de IM y
los modelos declarados de TR. Las sesiones anteriores conservan las reglas
legacy y no leen esta declaracion.

Residual explícito: coexisten `role_models.REVISOR` /
`role_mapping.revisor = nan/mimo-v2.6-flash`, vigente para las rondas en curso
y congelado por d-08, y `celdas.im.revisor = claude-sonnet-5`, aplicable a los
siguientes despachos. La convergencia queda diferida a un ticket posterior.

## 2. Diseno (3 declaraciones + 1 resolvedor; sin tocar el despachador)
D1 CELDAS (im_cells en la config): cada celda = lista de SLOTS con selector, no con modelos. Ejemplo: celda IM_BILENTE = slot reviewer (backend opencode, family no claude, cuenta X) + slot builder_child (backend codex, cuenta Y, via delegate_task). Cambiar de modelo = editar el selector o su lista de preferencia con fallback; ARRANQUE, latido y briefs citan solo el NOMBRE de la celda.
D2 PANELES (lens_panels): cada panel = lista de slots con selector por atributos del registro (channel agent o api, fs si/no, family, lab, tier, cuenta) y cantidad. Ejemplo: PANEL_TICKET = 1 lente fs de familia distinta a la del builder + 1 lente solo texto de otra familia + 1 lente de otro lab. Cambiar de lentes = editar el panel o pasar --panel otro.
D3 POLITICA DE INDEPENDENCIA (una regla): ninguna lente comparte family con el builder del ticket; al menos una comparte lab distinto; cambiar de cuenta, backend o version no cuenta. Si no hay candidata, la ronda se marca no independiente en el veredicto.
R lens_panel.py (resolvedor, scripts/flight): lee panel + registro + el modelo REAL del builder (de un snapshot de t3_thread_configuration o del argumento) y emite el plan: lista de (profile, backend_key, variables de entorno de cuenta, tipo de bundle) y el script de lanzamiento. Los scripts de lanzamiento de rondas dejan de escribirse a mano: se generan. Los bundles (agent con ficheros, agent con material copiado, solo texto) los decide el atributo channel/fs de la clave.
## 3. Que cambia en el dia a dia
- Para elegir lentes MEDIO, la prioridad es codex luna 5.6, claude sonnet 5, mimo-v2.6-flash y deepseek-v4-flash. Solo cambia la selección de lente; no cambia la configuración de IM ni TR. Cuando ambas cuentas estén disponibles, alvarovans tiene preferencia sobre brabander.
- Cambiar una lente: editar una linea del panel (o su selector). Cambiar la cuenta de un proveedor: una linea en la tabla de cuentas. Cambiar la celda del IM: editar la celda. Nada de eso toca prompts, ARRANQUE ni scripts.
- ARRANQUE y briefs: una frase con el nombre de la celda y del panel; el contenido sale del canon (render, como render_latido).
## 4. Cableado
rotate_coordinator rechaza un relevo cuyo ARRANQUE no cita la celda y el panel vigentes; registry_ops alta de un IM guarda celda y slots resueltos; la supervisora compara hilos reales (t3_thread_configuration) con la celda (script sobre snapshot).
## 5. Riesgos y limites
- Un selector demasiado flexible esconde cambios: el plan resuelto se imprime y se guarda en el ledger del vuelo con su hash.
- family y lab estan en el registro pero hay que revisarlos (BA253 claude y BA254 codex tienen family igual al backend, no al modelo).
- Alcance minimo propuesto: D3 + R + D2 para lentes primero (el dolor de hoy); D1 despues de que el usuario decida U1.
## 6. Pendiente
Ratificar este diseno, decidir U1/U3, abrir ficha (DISENO_PRIMERO) y despues implantacion con IM segun la celda decidida.

## Cadena anidada experimental
- Estado: EXPERIMENTAL autorizada, NO ratificada.
- Que es: en la celda del TR el supervisor mimo (orden vigente del usuario d99b0f8a-8136-49e2-8062-f7a85f014c9d, 2026-11-12; los brazos medidos hasta el 2026-11-13, TR-55 y TR-56, usaron supervisor glm) redacta cada seccion por una cadena de dos niveles con delegate_task: el hijo redacta la seccion y lanza al nieto comprobador; el nieto verifica (ASCII puro, tamano maximo por seccion, una clausula por fila, comandos de matriz hermeticos, ejecucion en lectura de lo comprobable) y escribe sus hallazgos en un fichero de check; el hijo aplica los hallazgos reales y entrega la version final. Cadenas: A (supervisor mimo, hijo gemma4, nieto qwen) y B (supervisor mimo, hijo qwen, nieto gemma4). Reparto decidido el 2026-11-13 (OK del usuario a la pasada de CO-87; opcion de dos lineas por partes): DOS LINEAS, A y B, cada una con partes DISTINTAS de las secciones del TR (ninguna seccion se redacta en las dos cadenas), en lugar de una sola cadena o de las dos cadenas sobre todas las secciones. Dentro de cada linea las secciones van en SECUENCIA, con tope ORIENTATIVO de nietos qwen vivos en vuelo (el sistema aguanta 3 en paralelo segun indica el usuario; lo importante es la verificacion por FICHERO).
- Reglas de fallo: 2 intentos de cadena por seccion; tras dos fallos el supervisor diagnostica por fichero, corrige la tarea o el troceo y relanza correctamente con 2 intentos nuevos; solo si fallan tambien esos dos, la seccion pasa al triador simple (un hijo sin nieto), declarandolo. Verificacion SIEMPRE por FICHERO (el summary final puede ser solo el preambulo del verificador).
- Evidencia: la REVISION del ticket lleva una seccion CADENA con quien redacto, quien comprobo, intentos y hallazgos reales por seccion.
- Que NO cambia: la fila P35 de vuelo_pilares.md y la fila P36 (no se editan), el roster y el gate check_cell_conformance; el registro sigue declarando el triador del canon vigente.
- Gobierno de la celda: el REVISOR de la celda gobierna a sus subagentes. Todo hijo que comprueba o redacta es de OTRA familia que el autor del texto que toca.
- Receta medida el 2026-11-17: desde un llamador mimo, usa `delegate_task` con `mode: async`, SIN CAMPOS NUMERICOS (en particular, `timeoutMs` falla porque mimo los emite como texto; gemma4 si los admite) y un objeto `target` con `providerInstanceId` y `model`.
- Control positivo: remite a `OPERACION_EN_CURSO_CO-114.md` l.80-82.
- Caducidad: 2026-11-21 si no hay al menos 3 secciones medidas por brazo con un verificador CIEGO AL BRAZO (el verificador no sabe de que cadena procede la seccion). Ampliada por el usuario el 2026-11-13, mensajes f57d6ff6-fee4-483f-9da5-bd6f3feb7009 (peticion) y 2a6dc27f-8c54-4ef8-b24b-5f605b72102d (confirmacion de 7 dias; antes: 2026-11-14).
- Ratificacion: SOLO con decision explicita del usuario sobre la medicion acumulada.

## 7. Retirada de Kilo y catalogo de dos fuentes (WOT-2026-222a)
El guard de rol de `send_to_profile` (`enforce_profile_policy` en scripts/ensemble_dispatch.py) y el checker de catalogo `scripts/check_ensemble_profile_catalog.py` (dos fuentes: `.agent/config/agents.json` del motor y un snapshot de `opencode models` / `kilo models` via `scripts/refresh_ensemble_model_catalog.py`) son la fuente de verdad operativa de esa politica; este documento solo apunta a ellos y no repite su contrato (X-09).
