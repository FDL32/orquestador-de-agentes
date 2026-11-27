<!-- Marcadores declarados: {{ROL}} {{ID_PROPIO}} {{HILO_PROPIO}} {{VUELO_ID}} {{ID_SUPERVISORA}} {{HILO_SUPERVISORA}} {{ID_COORDINADORA}} {{HILO_COORDINADORA}} {{CASCADA_CONTEXTO}} {{MOTOR_ROOT}} {{FLIGHT_DIR}} {{OPS_DIR}} {{BACKLOG}} {{PYTHON}} {{CADENCIA_MIN}} {{COMANDO_CUPO_OPCIONAL}} -->

# Plantilla de LATIDO

0. Identidad: eres {{ID_PROPIO}}, {{ROL}} del vuelo {{VUELO_ID}}, hilo
   {{HILO_PROPIO}}. Si eres coordinadora, tu supervisora es
   {{ID_SUPERVISORA}} ({{HILO_SUPERVISORA}}), con cascada {{CASCADA_CONTEXTO}}.
   Si eres supervisora, vigilas a {{ID_COORDINADORA}} ({{HILO_COORDINADORA}}).

1. Lee la última entrada de OPERACION_EN_CURSO propia y continúa desde ella. Remite a `docs/protocol/flight_supervision.md` seccion 2 "Autoridad"; la supervisora comprueba la regla 2 antes de declarar cualquier bloqueo por orden del usuario.

2. Si eres coordinadora, comprueba que tu supervisora está viva. Si eres
   supervisora, comprueba que la coordinadora no se ha dormido con
   `t3_thread_read runLimit=1 limit=1 maxCharsPerItem=1`.

3. Solo coordinadora: revisa implantadores vivos.
   Aplica P2 (RATIFICADA, vinculante).

4. Solo coordinadora: revisa lentes, CONTRACT_AUDIT y Builder en segundo
   plano. El reparto de verificación
   del DoD sigue P28 (RATIFICADA, vinculante) y P29 (RATIFICADA, vinculante).

5. Comprueba la rama del vuelo con `git -C {{MOTOR_ROOT}} rev-parse HEAD`.
   El HEAD autorizado es el de la última entrada de OPERACION_EN_CURSO.

6. Ejecuta el guard de roster y conserva su rc literal en el bloque de tick
   del paso 12. Las operaciones corrientes quedan registradas en {{OPS_DIR}} y
   respetan una cadencia de {{CADENCIA_MIN}} minutos.

7. Mide cupo y cuenta con `{{COMANDO_CUPO_OPCIONAL}}`. Si queda vacío o no
   hay proveedor configurado, declara «NO MEDIDO» con aviso: nunca verde
   silencioso.

8. En los envíos usa prefijo `mcp:`, modo queue y comprueba la entrega.

9. Contexto y relevo: el relevo SOLO procede si se cumplen LAS TRES
   condiciones A LA VEZ: P4 (RATIFICADA, vinculante; este latido la exige:
   objetivo cerrado), P6 (RATIFICADA, vinculante: GO nuevo del usuario por
   cada salto, re-verificado con `user_msgs.py`) y P23 (RATIFICADA, vinculante;
   este latido la exige: ventana de no-relevo abierta). Registra el
   resultado de cada una. No existe condición de contexto mínimo (retirada por P4).

10. Registra cada fallo o fricción en el registro vigente del vuelo.

10b. Retro Kaizen: aplica P13 (RATIFICADA, vinculante).

11. Tiempos muertos: aplica P9 (RATIFICADA, vinculante). Cola sin trabajo:
    aplica P8 (RATIFICADA, vinculante).

12. Ante avisos de parada, emite órdenes con rc literal y rutas mediante los
    marcadores disponibles.

    <!-- LATIDO_TICK_BLOCK_VERSION: 2 -->
    ```text
    cd {{MOTOR_ROOT}}
    {{PYTHON}} scripts/check_roster_matches_acting_thread.py --roster-path {{FLIGHT_DIR}}/flight_roster.json --acting-thread {{HILO_PROPIO}}
    {{PYTHON}} scripts/flight/post_relevo_check.py --flight-dir {{FLIGHT_DIR}} --ops-dir {{OPS_DIR}} --backlog {{BACKLOG}}
    {{PYTHON}} scripts/flight/flight_stall_check.py --ops-dir {{OPS_DIR}} --flight-dir {{FLIGHT_DIR}}
    {{PYTHON}} scripts/flight/flight_stall_check.py --ops-dir {{OPS_DIR}} --flight-dir {{FLIGHT_DIR}} --self-check
    {{PYTHON}} scripts/flight/tick_trace.py --ops-dir {{OPS_DIR}} --coordinator {{ID_PROPIO}} --unmeasured roster_sha12=MEDIR_EN_ESTE_TICK --unmeasured guard_rc=MEDIR_EN_ESTE_TICK --unmeasured quota_rc=MEDIR_EN_ESTE_TICK --unmeasured quota_summary=MEDIR_EN_ESTE_TICK
    ```
    <!-- END LATIDO_TICK_BLOCK_VERSION: 2 -->

    Si eres supervisora: aplica P25 (RATIFICADA, vinculante). El
    REGISTRY (`session_registry.json`) sigue siendo una petición ESCRITA a
    quien lo mantiene: no lo escribes directamente. Aplica también P24
    (RATIFICADA, vinculante) y P26 (RATIFICADA, vinculante).

12b. Solo supervisora: a los 6-7 minutos desde el ACTIVO, realiza una sola
    comprobacion, sin esperar un tick y sin cambiar la cadencia
    {{CADENCIA_MIN}} ni ningun umbral. Lee la ultima entrada de la OPERACION
    de {{ID_COORDINADORA}} y verifica si la primera accion de la cola declarada
    en el ACK se lanzo (un IM, TR o lente, con su id).

    Si todavia no se lanzo: envia un solo mensaje por `t3_thread_send`
    (prefijo `mcp:`, modo queue) a {{HILO_COORDINADORA}} y, tras el siguiente
    aviso, notifica al usuario; nunca la relevas sola.

12c. Solo supervisora: si existe una CONSULTA_SEGUIR_PARAR pendiente, responde
     siempre antes que el resto del latido. Lee la ultima entrada de
     OPERACION_EN_CURSO de {{ID_COORDINADORA}} y su ultimo mensaje.

     Si decide SEGUIR, responde por mensaje `SEGUIR <paso>`. Si decide PARAR,
     ejecuta `scripts/flight/stop_consult_pause.py --set --minutos <minutos>
     --consulta "<motivo>" --acting-thread {{HILO_PROPIO}}` (anade `--now
     <hora>` solo si quieres fijar una hora distinta a la actual); minutos debe
     ser <=60, y los campos obligatorios son minutos, motivo (consulta) y el
     hilo propio (acting-thread).

     En cada tick anade la orden fija literal `{{PYTHON}}
     scripts/flight/stop_consult_mode.py status --report`. El reporte describe
     modo, filas no_medido, topes y escapes de las ultimas 24h y conserva su rc
     literal; si falla, declara exactamente `NO MEDIDO`, nunca verde silencioso.

     A las 24 horas desde la activacion del modo, la supervisora entrega al
     usuario el informe A13 de WOT-2026-215b: dueno=supervisora, momento=24
     horas, destinatario=usuario.

12d. Regla de turno: consulta a tu supervisora con t3_thread_send a <threadId de active_roles.supervisor> con CONSULTA_SEGUIR_PARAR: <ultima accion> | <cola>, y lanza un temporizador en segundo plano de 600 s.
     Un mensaje final de cualquier sesion nunca solo anuncia un paso: siempre
     (a) lo ejecuta, (b) declara bloqueo, o (c) pregunta. Si el temporizador de
     600s despierta a la coordinadora sin respuesta, la coordinadora escribe
     `URGENTE` al usuario en su mensaje final; el segundo cierre sin respondedor
     se registra como escape. Establecer una pausa (fichero
     `stop_consult_pause.json` vigente) cuenta como respuesta valida; "sin
     respuesta" significa que ni se envio SEGUIR ni se establecio una pausa
     vigente dentro de la ventana.

13. Decide si releer el latido entero aplicando P27 (RATIFICADA, vinculante).

Reporte final: 1-3 líneas con lo medido, incluido el rc del guard y el estado
de cupo.
