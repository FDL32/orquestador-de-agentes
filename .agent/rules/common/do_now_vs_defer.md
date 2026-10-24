## Hacer ahora vs aplazar (criterio de decision)

El coste de APLAZAR **no es cero**: fichar "para la proxima sesion" cuesta prompt de arranque, recarga de contexto, re-medicion y revalidacion de premisas, y sobre todo **asciende el diagnostico de hoy a premisa heredada sin verificar**. Pero ese coste NO autoriza a perseguir parches que degeneran.

**Asimetria (regla de oro, y mas en autonomo):** los gates de abajo son un filtro para PERMITIR hacer ahora, **nunca una obligacion de hacerlo**. Ante duda no resuelta POR EVIDENCIA, **aplazar gana**. Si el trabajo se sale del objetivo del ticket, se ficha y pasa a la sesion siguiente. El sistema debe ser fuente de soluciones, no de problemas: un arreglo dudoso metido a presion es un problema nuevo con commit.

**Cada gate se responde con un ARTEFACTO, no con un juicio.** Un gate que se contesta con una opinion se relaja solo en cuanto el agente quiere avanzar (misma enfermedad que "aplicate tu propia vara"). Si no puedes pegar el artefacto, el gate NO pasa.

### Hazlo ahora SOLO si cumple los 8

1. **Localizacion EJECUTADA EN LA RUTA PRODUCTIVA.** No basta "se la linea"; **ni siquiera basta "lo ejecute"**. Aplica la **equivalencia de ruta productiva** de CEM: declara actor real, launcher real, shell, cwd, PATH/env, fichero/config leido, y **por que ese probe reproduce la ruta que corre en produccion**. Si no la reproduce es **evidencia exploratoria** y este gate **NO pasa** (orienta, no cierra). Artefacto: `command:` + `exit_code:` + `shell/cwd/env:` + la frase de equivalencia. Si dos probes se contradicen, **el conflicto ES el hallazgo** (CEM): resuelvelo antes de tocar nada.
2. **DoD con dientes.** Existe test/probe que falla HOY con el bug y pasa con el fix, o mutacion **alcanzable** definida (un test que no puede ALCANZAR la rama que muta no cuenta). Artefacto: node-id + rc rojo previo.
3. **Una superficie acotada.** Una superficie, no una familia. Artefacto: lista de ficheros a tocar (numero cerrado).
4. **Arquitectura existente.** Conecta una pieza ya prevista o corrige una desviacion local; no inventa subsistema. Artefacto: la ruta del mecanismo que extiendes.
5. **Cadena fresca.** "Desbloquea la cadena" solo vale si el DAG/triage se revalido EN ESTA SESION; un DAG en disco caduca solo (WOT-2026-023t). Si esta caducado, **re-triage primero**. Artefacto: fecha/SHA del triage.
6. **Cabe completo:** fix + tests + mutation + gates + commit + review proporcional. Artefacto: la balanza de abajo.
7. **Bisect-safe:** cada commit publicable queda verde en su propio HEAD.
8. **Sin decision humana pendiente.** Trade-off de producto, politica o arquitectura -> se pregunta o se ficha.

### STOP de degeneracion (durante el arreglo)

Si tras el primer parche aparece cualquiera de estos, **parar y re-planificar**: superficie nueva no prevista; heuristica nueva; mas de un fichero/familia adicional; el test inicial no alcanza la rama real; el fix empieza a parecer diseno de sistema. **No parchear el parche:** ficha el alcance nuevo o abre sesion propia (WOT-2026-024u: de 3 lineas a "disenar un analizador estatico" en 5 parches; salio a WOT-2026-025c).

### Aplazalo si

No hay probe ejecutado en contexto de produccion; el DoD es aspiracional; requiere medir la flota completa o datos externos; mezcla familias de commits; depende de decision humana; el DAG esta caducado; la solucion correcta es diseno nuevo; no puede quedar bisect-safe; o el contexto es largo y el riesgo de falso-verde sube.

### Balanza minima obligatoria (con cifras, no adjetivos)

Sin al menos una cifra por columna la balanza es sesgo de presente: el agente subestima siempre lo hipotetico.

| Hacer ahora | Aplazar |
|---|---|
| ficheros tocados (n) | re-medicion requerida: si/no |
| tests/probes nuevos (n) | contexto a recargar |
| tiempo/review estimado | riesgo vivo si se deja |
| blast radius | sesiones futuras estimadas (n) |

### Dos reglas durables

> Detalle en [hacer_ahora_vs_aplazar_dos_reglas_durables](docs/protocol/hacer_ahora_vs_aplazar_dos_reglas_durables.md).

### Claim causal vs hecho medido (WOT-2026-038k)

Medido 2026-07-20 (3a ola, vuelo de gobierno): tres teorias causales distintas
sobre un mismo fallo observado sobrevivieron varias pasadas de revision hasta
que alguien las MIDIO. Dos ejemplos reales: "el push esta bloqueado por el
clasificador" (heredado del prompt de arranque, propagado a 3 artefactos) se
refuto con `git push --dry-run` + push real; "el clasificador gatea el egress
de payload nan" se habia construido sobre 3 denegaciones reales pero NO fue
reproducible al reintentar el MISMO bundle con el mismo fan-out de 8 lentes
(8/8 por contenido).

**Definicion operativa:**
- **Hecho medido**: cita `command:` + salida/`exit_code:` reproducible. Es lo
  que ya exige el gate 1 de la lista de arriba.
- **Claim causal**: explica el PORQUE de un hecho medido. Es la parte NO
  medida -- aunque se apoye en hechos reales, la inferencia que los conecta
  no lo es.

**Patron de fallo:** un claim causal se escribe como hecho en un artefacto
durable (batch_run, parte de cierre, prompt de arranque de la sesion
siguiente) y viaja sin marca de que es inferido. La sesion siguiente lo lee
como premisa ya establecida y deja de cuestionarlo -- exactamente la
"premisa heredada sin verificar" del parrafo de arriba, pero con un
mecanismo de propagacion mas preciso: no es solo que aplazar tenga coste, es
que una inferencia sin medir puede CRISTALIZAR en hecho por mera repeticion
en texto.

**Decision de diseno (DoD b de WOT-2026-038k): NORMA, no barrera cableada.**
Se evaluo anadir un check automatico que exigiera marcar explicitamente los
claims causales como `INFERIDO` en los artefactos de cierre, y se DESCARTO
por riesgo declarado de burocracia: distinguir programaticamente "explica un
mecanismo" de "narra un hecho" en prosa libre no tiene una señal sintactica
fiable (ver `obs-grepping-for-a-word-is-not-checking-for-the-fact` en
memoria -- un grep de palabras clave como "porque"/"causa" produciria ruido
masivo). El eslabon fragil citado por el ticket (el mismo agente que escribe
la causa es quien juzgaria si esta medida) tampoco lo resuelve un check
local: requiere la misma pasada adversarial de Revisor fresh-context que ya
exige el flujo Manager->Builder->Revisor para cualquier cierre de ticket no
trivial -- la barrera YA EXISTE a nivel de proceso, no falta construir una
nueva. Si una familia de claims-sin-medir concretos se repite de forma
medible (no una vez), reabrir como DoD cableado con el patron exacto que lo
justifique.
