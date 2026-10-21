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

