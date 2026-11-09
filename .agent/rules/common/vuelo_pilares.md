# Índice de pilares del protocolo de vuelo infinito

| Pilar | Frase de la regla | ESTADO | messageId | fuente larga | mecanismo que la cumple | a quien preguntar |
|---|---|---|---|---|---|---|
| P1 | Dos implantadores (IM) en paralelo: objetivo y tope máximo, NO obligatorio; FLT disjuntos y cuentas codex distintas. | RATIFICADA | c38d20f3-796a-4f56-ae3d-50c09952ce25 | PLAN_VUELO_INFINITO_BORRADOR_v3_20261106.md | minutos con 2 IM vivos / minutos con >=2 fichas aptas efectivas | coordinadora activa |
| P2 | IM fresco por ticket: un ticket por IM, rotando; tope de IM sin asentar = 2. | NO RATIFICADA |  | ADJUDICACION_imfresco_CO47_20261106.md | tickets por hilo IM (objetivo 1) | coordinadora activa |
| P3 | Protocolo de escalada: IM -> coordinadora -> supervisora (si falta contexto) -> bucle de gobierno -> usuario; documentar y continuar, nunca bloquear esperando. | RATIFICADA | f6d35bfa-adad-4384-a20c-41792f309de2 | ESCALADO_VUELO_INFINITO_20261106.md | consultas por clase A-D y su latencia | coordinadora activa |
| P4 | Relevo de coordinadora al cerrar el objetivo: se releva SIEMPRE al cerrar el objetivo, sin mínimo de contexto exigido. | NO RATIFICADA |  | NORMA_RELEVO_AL_CERRAR_OBJETIVO_20261105.md | contexto de la saliente al relevar / 600000 | coordinadora activa |
| P5 | Relevo según progresión de contexto: el objetivo se dimensiona al contexto real, no a un umbral fijo. | NO RATIFICADA |  | PROPUESTA_OBJETIVO_POR_PRESUPUESTO_CONTEXTO_v2_20261106.md | contexto acumulado por ticket aceptado frente a estimación | coordinadora activa |
| P6 | Un salto de coordinadora al cerrar el objetivo en curso exige GO explícito y nuevo del usuario, verificado con user_msgs.py; relevo sin GO >60 min es parada. | RATIFICADA | 815a8c92-d9bc-4b14-9a55-0f8d9bdae792 | GO_RELEVO_24H_REGISTRO.md | GO restantes frente a saltos previsibles | usuario |
| P7 | Cambio de cuenta según tokens: al superar el umbral de preparación se prepara, al superar el umbral de cambio se cambian todos los hilos; ida secuencial nieta->madre->abuela y retorno inverso. Los umbrales vigentes viven en flight_roster.json/session_registry.json. | RATIFICADA | 360b9d8d-a25d-4094-9974-659fa60877e9 | NORMA_CUENTA_DEFINITIVA_20261105.md | ticks con cupo medido (rc 0); episodios de cupo alto sin acción según el umbral vigente en flight_roster.json/session_registry.json | coordinadora activa |
| P8 | Triaje si no hay ticket: si IM vivos <2 y no hay fila APTO con brief y FLT disjunto, se lanza un TR (triaje) en ese tick (H178). | RATIFICADA | bde976db-d3ba-41b9-a98c-2cc1830f8eda | HALLAZGOS_protocolo_vuelos_autonomos.md | minutos con IM<2, 0 TR vivo y 0 fila apta (objetivo: 0 por encima de 10 min) | coordinadora activa |
| P9 | Uso de tiempos muertos: mientras se espera algo, plantearse si se puede avanzar otra tarea de la cola. | RATIFICADA | 96c8ad52-4bf5-4bf7-ad4a-9b6d4cad698d | (sin fichero de propuesta dedicado; declarado en el paso 11 del LATIDO) | minutos de IM ocioso con cola pendiente | coordinadora activa |
| P10 | Higiene de hilos: nunca más de tres hilos de coordinadora sin asentar; tope 2 IM / 2 TR. | NO RATIFICADA |  | PLAN_VUELO_LARGO_8H_20261105.md | hilos sin asentar por tipo frente a sus topes | coordinadora activa |
| P11 | Subagentes: por la cuenta prioritaria mientras la proyección no pase del umbral vigente en flight_roster.json/session_registry.json; un subagente Claude nunca sustituye a una lente de revisión. | NO RATIFICADA |  | PLAN_VUELO_24H_BORRADOR_20261106.md | subagentes simultáneos <=2 | coordinadora activa |
| P12 | Documentación acotada: rotar y eliminar la documentación que genera el propio proceso pasado un tiempo, para que no crezca sin control. | NO RATIFICADA |  | CONSULTAS_DOCUMENTADAS.md | bytes y ficheros de diseño por hora | coordinadora activa |
| P13 | Kaizen: bitácora de mejora continua con retro por ola o cada 6 horas, máximo 5 entradas por retro; una entrada solo se marca VERIFICADA cuando el indicador se mide DESPUÉS. | RATIFICADA | 4c78b35c-e8f9-4343-b069-3d997158065d | BITACORA_KAIZEN_vuelo24h.md | entradas K en VERIFICADA con el indicador movido | coordinadora activa |
| P14 | El usuario no es cuello de botella: documentar y continuar sin AskUserQuestion; la cadena nunca espera bloqueada la respuesta del usuario. | NO RATIFICADA |  | ESCALADO_VUELO_INFINITO_20261106.md | minutos de coordinación detenida esperando al usuario | coordinadora activa |
| P15 | Continuidad 24h: PC sin suspensión, canal T3 abierto, aviso externo y copia de seguridad periódica. | NO RATIFICADA |  | PLAN_VUELO_24H_BORRADOR_20261106.md | minutos de PC suspendido / minutos de vuelo | coordinadora activa |
| P16 | Una sola ronda de lentes de revisión a la vez; el nonce lo emite SOLO la coordinadora, tras el último commit. | NO RATIFICADA |  | PLAN_VUELO_24H_BORRADOR_20261106.md | rondas de lentes concurrentes (objetivo 0) | coordinadora activa |
| P17 | La suite canónica completa corre UNA sola vez, solo para publicar; entre medias, gate por merge (focal + 2 lentes). | NO RATIFICADA |  | PLAN_VUELO_INFINITO_BORRADOR_v3_20261106.md | suites completas ejecutadas en el vuelo | coordinadora activa |
| P18 | Sin push a main hasta que el usuario lo diga explícitamente. | NO RATIFICADA |  | BRIEF_vuelo.md | ninguna rama remota contiene el HEAD del vuelo | usuario |
| P19 | Cola alimentada por sesiones de diseño autónomas, que SOLO producen ficha o contrato congelado, nunca código. | NO RATIFICADA |  | PLAN_VUELO_INFINITO_BORRADOR_v3_20261106.md | sesiones de diseño lanzadas desde el inicio del vuelo | coordinadora activa |
| P20 | Coste de coordinación por ticket acotado: objetivo de N tickets o X k de contexto por tenencia, estimación ~170k +/-30k por ticket. | NO RATIFICADA |  | BITACORA_KAIZEN_vuelo24h.md | contexto consumido por ticket cerrado | coordinadora activa |
| P21 | Supervisión: latido de la coordinadora cada 15 minutos y de la supervisora cada 30 minutos. | NO RATIFICADA |  | NORMA_CUENTA_DEFINITIVA_20261105.md | huecos entre ticks de latido >30 min | supervisora |
| P22 | Registro citable de eventos del vuelo en un journal y en un fichero de incidencias. | NO RATIFICADA |  | BRIEF_vuelo.md | eventos registrados en el journal | coordinadora activa |
| P23 | Ventana de no-relevo: solo se releva sin Builder vivo, sin CONTRACT_AUDIT abierto, sin LISTO_PARA_INTEGRAR sin fusionar y sin nonce ni lente de revisión en vuelo. | NO RATIFICADA |  | NORMA_RELEVO_AL_CERRAR_OBJETIVO_20261105.md | minutos con 0 IM atribuibles a la espera del relevo | coordinadora activa |
| P24 | Cierre del relevo y terna: la terna presente es orquestador, supervisor y UN ancestro directo; tras el ACTIVO, la coordinadora resultante asienta (settle) todo CO fuera de la terna sin tocar un hilo en uso (K-93); K-93 manda sobre el punto (e) de la ficha de higiene de hilos (146a). | RATIFICADA | 937a5d9e-ac1d-44cf-89be-f1d644259f88 | ANALISIS_HIGIENE_HILOS_Y_PROPUESTA_20261106.md | norma sin cablear hasta que el rotador versionado incorpore el cierre | coordinadora activa |
| P25 | Rotador: lo lanza la supervisora vigente; ninguna sesión fuera del roster lo ejecuta ni lo mantiene. | RATIFICADA | 937a5d9e-ac1d-44cf-89be-f1d644259f88 | PROPUESTA_FUNCIONES_SOSTENEDORAS_Y_CIERRE_DE_RELEVO_v2_20261108.md | norma sin cablear | supervisora |
| P26 | Funciones sostenedoras: toda función que sostiene el vuelo tiene rol en el roster con titular, suplente y aceptación, vigilancia de contexto con los hitos vigentes, ejecutor del cierre y dueño declarado de cada automatización que la sostiene; sin los cuatro no existe y la hace un script. | RATIFICADA | 937a5d9e-ac1d-44cf-89be-f1d644259f88 | PROPUESTA_FUNCIONES_SOSTENEDORAS_Y_CIERRE_DE_RELEVO_v2_20261108.md | norma sin cablear | coordinadora activa |
| P27 | Relectura del latido: se puede omitir la relectura entera SOLO si el sha12 coincide con el de la última lectura entera Y la sesión no ha compactado desde entonces Y no cambió el rol; en cualquier otro caso se lee entero. | RATIFICADA | 937a5d9e-ac1d-44cf-89be-f1d644259f88 | PROPUESTA_FUNCIONES_SOSTENEDORAS_Y_CIERRE_DE_RELEVO_v2_20261108.md | norma sin cablear | coordinadora activa |
| P28 | La verificación del DoD frase por frase es del REVISOR de la celda mediante una matriz (cláusula, comprobación, ámbito, conteo esperado, conteo medido, control positivo); la coordinadora comprueba cobertura (cuenta las cláusulas contra la ficha), repite una muestra y hace la integración previa, los mutantes, el nonce y las lentes. | RATIFICADA | 71ce07a9-cadf-4882-85bb-b408632139ec | PROPUESTA_OPTIMIZACION_SIGUIENTE_VUELO_v1_20261108.md | cláusulas del DoD cubiertas por la matriz del revisor frente a cláusulas totales de la ficha (cobertura) | coordinadora activa |
| P29 | Una caja sin matriz ejecutada por el revisor no se acepta. | RATIFICADA | 71ce07a9-cadf-4882-85bb-b408632139ec | PROPUESTA_OPTIMIZACION_SIGUIENTE_VUELO_v1_20261108.md | cajas aceptadas por la coordinadora sin matriz del revisor adjunta (objetivo 0) | coordinadora activa |
| P30 | Celda del IM: cada IM es una celda formada por una sesion revisora (nan) y un builder codex hijo lanzado con delegate_task; un IM NUNCA se lanza como sesion unica Manager+Builder. Asignacion vigente por el momento: IM#1 con revisor deepseek (nan), IM#2 con revisor glm 5.3 flash (nan), builder codex en ambos (modelo y cuentas segun las ordenes permanentes: cuentas codex distintas, sin el modelo sol). | RATIFICADA | fe7a644c-0f51-491f-b7ec-e021109b0682 | docs/protocol/sistema_agnostico_celdas_y_lentes.md | norma sin cablear hasta la ficha del resolvedor; mientras tanto la coordinadora contrasta ARRANQUE, brief y latido antes de lanzar | coordinadora activa |
| P31 | Sistema agnostico: las celdas del IM y los paneles de lentes se DECLARAN como configuracion (huecos con selector por atributos del registro de backends: canal, ficheros, familia, laboratorio, cuenta), no se escriben en prosa ni en scripts a mano; cambiar una lente, un modelo o una cuenta es editar una declaracion; un resolvedor genera el plan de lanzamiento y lo guarda con su hash. | RATIFICADA | fe7a644c-0f51-491f-b7ec-e021109b0682 | docs/protocol/sistema_agnostico_celdas_y_lentes.md | norma sin cablear hasta la ficha del resolvedor | coordinadora activa |
| P32 | Ante conflicto entre fuentes (ARRANQUE, brief del ticket, latido, canon) antes de lanzar un IM o una ronda: parar, no elegir la que se tiene delante; manda el canon y, si el canon no resuelve, se pregunta al usuario. Las ordenes permanentes del ARRANQUE salen del canon, no se copian a mano. | NO RATIFICADA |  | docs/protocol/sistema_agnostico_celdas_y_lentes.md | norma sin cablear; propuesta: el rotador rechaza un relevo cuyo ARRANQUE cambie las ordenes estables sin una linea CAMBIO con messageId | coordinadora activa |
| P33 | Independencia de lentes por familia: ninguna lente de una ronda comparte familia de modelo con el builder o el revisor del ticket, al menos una lente es de otro laboratorio, y cambiar de cuenta, backend o version no cuenta como independencia; sin candidata se marca la ronda como no independiente. | NO RATIFICADA |  | docs/protocol/sistema_agnostico_celdas_y_lentes.md | norma sin cablear; propuesta: el lanzador de rondas lee el modelo real del IM y sustituye la lente de su familia | usuario |

## Precedencia

De mayor a menor:

1. Orden del usuario ratificada, con messageId comprobable con user_msgs.py (incluidas las que fijan vigencias provisionales).
2. Lo que corre: AGENTS.md, los prompts versionados del motor, scripts/flight y sus tests.
3. flight_roster.json y session_registry.json, SOLO para estado y números (quién es quién, topes, cuentas): son la fuente única de cifras.
4. Este índice (vuelo_pilares.md).
5. Normas largas de diseño del vuelo con cabecera ESTADO: VIGENTE.
6. OPERACION_EN_CURSO, ARRANQUE y LATIDO de cada coordinadora: registran estado y remiten, nunca crean reglas.

Desempate dentro del mismo nivel: gana la que lleva ratificación explícita más reciente; si ninguna la lleva, la que declara SUPERADA a la otra; si tampoco hay desempate, se aplica la interpretación más restrictiva, se anota en el registro de consultas documentadas del vuelo y se continúa.

## Gramática de la cabecera ESTADO (ficheros de diseño del vuelo)

Como referencia, los ficheros de diseño de un vuelo llevan como PRIMERA línea, en ASCII y mayúsculas, sin fecha ni hora ni threadId, una cabecera que valida esta expresión regular:

`^ESTADO: (VIGENTE|BORRADOR|HISTORICO|SUPERADO POR \S+|SUPERADO PARCIALMENTE \(.+\) POR \S+)$`

Ejemplos válidos:

- `ESTADO: VIGENTE`
- `ESTADO: BORRADOR`
- `ESTADO: HISTORICO`
- `ESTADO: SUPERADO POR LATIDO_CO-54_v7.1_20261108.md`
- `ESTADO: SUPERADO PARCIALMENTE (s.3 a s.7) POR NORMA_CUENTA_V2_20261105.md`

Ejemplos inválidos:

- `Estado: VIGENTE`
- `ESTADO VIGENTE` (sin dos puntos)

Esta gramática no aplica al propio `vuelo_pilares.md`, que es un fichero versionado del motor, no un fichero de diseño del vuelo. El validador para estos ficheros será `scripts/flight/check_vuelo_canon.py`, fuera de esta ficha (fase F1b; no se crea aquí).
