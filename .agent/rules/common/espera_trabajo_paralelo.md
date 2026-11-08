ESTATUS: NORMA (no barrera). Ficha WOT-2026-160o (2026-11-08). Origen: P9 (vuelo_pilares.md, RATIFICADA, 96c8ad52-4bf5-4bf7-ad4a-9b6d4cad698d) y orden del usuario (mensaje 63ce37dc-9be5-47f2-af14-30ac7530dc36). Citado desde AGENTS.md ("### Espera => trabajo avanzable").

# Espera => trabajo en paralelo no perjudicial

1. Por que: 2026-11-06 CO-48 y el IM de 152q esperaron una hora sin lanzar; 2026-11-08 CO-56 cerro tres turnos de espera con "sigo esperando" y el usuario pidio la enumeracion dos veces.
2. Subordinacion: la enumeracion es obligatoria; hacer cada item pasa los 8 gates de `.agent/rules/common/do_now_vs_defer.md` (Hacer ahora vs aplazar; aplazar gana ante duda). El trabajo de espera NO es un arreglo: solo lectura, preparacion o registro, sin alterar el proceso principal ni decidir por el usuario.
3. Ejemplos por rol (pocos):
   - Coordinadora: verificar GO, registrar pendientes, preparar scope y mutantes, hallazgos, handoff, registrar la limpieza pendiente.
   - Implantador: preparar mutantes y la matriz del DoD mientras corre el builder.
   - Manager: leer el diff, preparar preguntas de revision.
   - Builder: ejecutar un gate focal, releer el DoD.
4. Interrupcion: al llegar el resultado esperado se detiene el trabajo de espera y se atiende.
5. Coste como registro: mide el contexto propio con `ctx_usage.py` (hoy vive en la carpeta de operaciones del vuelo, fuera del repo; el LATIDO declara su ruta), antes y despues de cada turno de espera. El tope se fija tras medir dos vuelos, sin umbral inventado.
6. Antipatrones:
   - Cerrar con "sigo esperando" sin lista. MEDIDO: `diseno/OPERACION_EN_CURSO_CO-56.md` entrada #31 (2026-11-08 11:56) -- CO-56 cerro tres turnos asi (tras IM-94 11:41, tras IM-95 11:47, tras IM-95 11:58) y solo enumero cuando el usuario lo pidio (mensajes f697e88c-328c-4376-be6b-a0d0a0cf18e8 y 63ce37dc-9be5-47f2-af14-30ac7530dc36).
   - Escribir una hora que no sale de `date`. MEDIDO: `diseno/APRENDIZAJE_RELEVOS_ENCADENADOS_20261105.md:357` (fila K-67, CO-40: horas sin medir en 4 mensajes) y `diseno/OPERACION_EN_CURSO_CO-15.md:174` (entrada 42: horas inventadas en 2 entradas).
   - Tocar el FLT de un IM vivo. Regla preventiva, SIN incidente medido en este vuelo.
   - Mutar el HEAD con una suite en curso. Regla preventiva, SIN incidente medido en este vuelo.
   - Lanzar mas de los topes. MEDIDO: `HALLAZGOS_protocolo_vuelos_autonomos.md:46` (H29: maximo 2 qwen3.6 concurrentes) y ficha WOT-2026-146a (topes 2/2/3, pendiente de asentar por el usuario).
   - Hacer commits en el motor antes de la suite final. Ver `AGENTS.md`, seccion "Orden de trabajo: AGRUPA los commits, la suite va la ULTIMA (WOT-2026-026t)".
7. Lo que NO esta en la norma: lanzar triaje si hay menos de 2 IM (H178, pendiente de ratificacion del usuario).
8. Indicador: el de P9 (minutos de IM ocioso con cola pendiente) mas un contador nuevo (turnos de espera cerrados sin entrada sobre turnos de espera totales). Barrera futura: campo `idle_checklist` en `scripts/flight/tick_trace.py`, como ficha si el contador no baja a 0 en dos vuelos seguidos.
