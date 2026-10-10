---
contract_id: cid-agent-execution-modes-v1
status: frozen
---

# Modos de ejecucion multiagente

Nucleo portatil que define los modos de ejecucion disponibles para una sesion
de Claude Code que orquesta trabajo sobre tickets del backlog, el criterio de
PROPUESTA automatica de modo, y el protocolo de CAMBIO EN CALIENTE durante una
conversacion ya en marcha. Contenido normativo UNICO de este documento: nada
de lo de aqui se re-declara en la skill que lo invoca (`skills/agent-execution-
mode/SKILL.md`), que SOLO apunta (regla X-09 de este repo, ver AGENTS.md).

**Estado:** `frozen` (congelado tras 2 pasadas de bucle adversarial, ver
Seccion 6.1/6.2: 7 lentes la primera pasada, 4 lentes la segunda,
convergencia sin division real). Los criterios de este documento son
normativos -- un agente que lo lea los aplica, no los trata como
propuesta.

---

## 1. Los 3 modos

| Modo | Quien hace QUE | Cuando tiene sentido |
|---|---|---|
| **Tradicional** (Claude Code como Builder/Manager/Revisor, sin delegar a Kilo) | Claude Code lee codigo, implementa, escribe tests, revisa su propio diff o pide revision al usuario. Un unico agente hace todo el trabajo pesado. | Ticket suelto o lote pequeño (1-3 tickets); el ticket toca la allowlist de blast-radius-alto (Seccion 3); no hay Kilo CLI disponible; el usuario necesita trazabilidad inmediata linea a linea sin pasar por un informe intermedio. |
| **4 capas** (Capa 0 Claude Code orquesta, Capas 1/1.5/2 delegadas a `nan` via Kilo CLI) | Claude Code SOLO lanza procesos y lee resumenes/veredictos cortos (<500 palabras); Manager-nan triaje+contrato, Builder-nan implementa, Revisor-nan independiente revisa. Ver `PROMPT_ARRANQUE_vuelo_limpieza_backlog_4capas_20261010.md` (referencia canonica, Seccion 3) para el diseño completo ya implementado de este patron. | Vuelo largo (lote de 15+ tickets); Kilo CLI + perfiles `nan` (`channel: agent`, `backend: kilo`) confirmados disponibles; **NINGUN** ticket del lote toca la allowlist de blast-radius-alto -- si AL MENOS UNO la toca, el modo correcto para la sesion es **Intermedio** (nunca 4 capas puras con ese ticket incluido sin mas), ver Seccion 4. |
| **Intermedio** | Claude Code delega el TRIAJE/CONTRATO (Capa 1, Manager-nan) a Kilo para TODO el lote, pero IMPLEMENTA y REVISA el mismo (sin Capa 2 ni Capa 1.5 delegadas) los tickets que tocan la allowlist de blast-radius-alto. El resto del lote (tickets S/M fuera de la allowlist) sigue en 4 capas completas (Capa 2 y Capa 1.5 delegadas) dentro de la MISMA sesion. | Lote mixto: mayoria de tickets aptos para 4 capas, pero 1-2 tickets de alto impacto (ver allowlist, Seccion 3) donde Claude Code prefiere control directo de implementacion Y revision. |

**Regla dura (corregida tras bucle adversarial, Seccion 6 -- 3/4 lentes con
contenido señalaron riesgo de seguridad en la version anterior):** para un
ticket de la allowlist, el modo Intermedio NUNCA delega ni la
IMPLEMENTACION (Capa 2, Builder-nan) ni la REVISION (Capa 1.5, Revisor-nan)
a Kilo. Ambas las hace Claude Code directamente -- un Revisor-nan que nunca
implemento codigo de esa allowlist en la sesion actual carece del contexto
de diseño necesario para revisarla con la misma profundidad que exige la
allowlist (riesgo real, no solo de forma: confirmado por 3 lentes
independientes del bucle de gobierno de este documento). La UNICA
diferencia estructural entre Intermedio y 4 capas puro es que Intermedio
sigue delegando el TRIAJE/CONTRATO (Capa 1) de los tickets de la allowlist
-- Manager-nan puede clasificarlos y redactar su contrato, pero ni
implementarlos ni revisarlos.

---

## 2. Señales de propuesta automatica (el agente PROPONE, el usuario CONFIRMA)

Al arrancar una sesion que vaya a orquestar trabajo sobre el backlog (o al
recibir una peticion de tamaño no trivial a mitad de conversacion), el
agente evalua estas 4 señales, en este orden de precedencia, y PROPONE un
modo con su razon en una frase -- nunca lo activa en silencio. El usuario
confirma o corrige en un unico intercambio (ver Seccion 5, mismo protocolo
que el cambio en caliente).

**Precedencia corregida (bucle adversarial, Seccion 6):** la peticion
explicita del usuario (señal 1) pesa MAS que las señales heuristicas (3-4),
pero NUNCA mas que la viabilidad (señal 2) ni que la regla dura de
seguridad del modo Intermedio (Seccion 1) -- un usuario no puede forzar 4
capas o Intermedio si Kilo no esta disponible, ni forzar que un ticket de
la allowlist se delegue a Builder-nan o Revisor-nan. Si el usuario pide
algo que viola la señal 2 o la regla dura, el agente lo declara
explicitamente ("Kilo no esta disponible, no puedo proponer 4 capas; uso
Tradicional") en vez de intentarlo y fallar a mitad.

1. **Peticion explicita del usuario.** Si el usuario ya nombro un modo por
   su nombre (p.ej. "usa las 4 capas", "hazlo tu directamente") en su propio
   mensaje de arranque o en cualquier mensaje posterior, esa señal pesa MAS
   que las heuristicas 3-4 -- el agente la respeta y solo confirma que la
   entendio, no vuelve a preguntar desde el criterio 3-4. Sigue subordinada
   a la señal 2 y a la regla dura de seguridad (parrafo anterior). **Cual
   protocolo aplica, segun el momento (bucle adversarial, segunda pasada):**
   una peticion en el mensaje de ARRANQUE de la sesion aplica esta Seccion 2
   completa (las señales 2-4 siguen actuando como verificacion de
   viabilidad/seguridad); una peticion a MITAD de un vuelo ya en marcha
   aplica el protocolo de cambio en caliente de la Seccion 5 (declaracion
   de modo saliente/entrante, "ronda en vuelo", etc.) en vez de repetir la
   Seccion 2 desde cero.
2. **Disponibilidad de Kilo CLI + perfiles `nan`.** Si `kilo --version`
   falla, o `.agent/config/agents.json` no tiene ningun perfil con
   `channel: agent` + `backend: kilo`, las 4 capas y el modo Intermedio NO
   son viables -- el agente propone Tradicional directamente, sin preguntar
   por las señales 3-4 (son irrelevantes si la herramienta no existe), y
   sin aceptar una peticion explicita en contrario (señal 1).
3. **Blast radius (allowlist de ficheros criticos).** La fuente de "que
   ficheros toca este ticket" es, en este orden de preferencia: (a) el
   `Files Likely Touched`/FLT ya declarado en el contrato o ficha del
   ticket si existe; (b) el triaje de la Capa 1 si ya corrio; (c) una
   lectura directa del cuerpo de la fila del backlog si ninguno de los
   anteriores existe todavia. El agente declara CUAL de las tres uso. Si el
   ticket (o CUALQUIER ticket del lote, en el caso de un vuelo) toca la
   allowlist declarada en la Seccion 3 segun esa fuente, el agente descarta
   4 capas PURAS para ese ticket -- propone Tradicional (lote pequeño) o
   Intermedio (lote grande con mayoria de tickets fuera de la allowlist).
4. **Tamaño del vuelo.** Si ninguna señal anterior decide, el agente cuenta
   el universo de tickets YA TRIADOS (nunca "estimados": si no hay triaje
   previo, el agente lo declara y cuenta solo lo que tiene fila real en el
   backlog): 1-3 tickets -> propone Tradicional; 15+ tickets -> propone 4
   capas; un numero intermedio (4-14) sin señal 1-3 decisiva es zona gris
   DECLARADA (el umbral de 15 es una heuristica de amortizacion del coste
   de orquestacion, no una medicion exacta -- se revisa si el bucle de
   gobierno de este documento, u otro posterior, mide un punto de corte
   distinto). En zona gris: si el lote es MIXTO (alguno de los tickets toca
   la allowlist), el agente sugiere Intermedio como default DENTRO de la
   misma pregunta (nunca lo activa sin confirmar); si el lote es limpio
   (ninguno toca la allowlist), el agente pregunta directamente sin
   proponer un default.

### 3. Allowlist de blast-radius-alto (reusa el criterio ya fijado)

Esta es la MISMA allowlist que la Seccion 3.1 del documento CANONICO del
patron 4 capas, `PROMPT_ARRANQUE_vuelo_limpieza_backlog_4capas_20261010.md`
(no `ARRANQUE_continuidad_vuelo_limpieza_backlog_4capas_20261010.md`, que
es un documento de continuidad de SESION distinto, nunca la fuente de la
allowlist) -- no se re-declara con criterio propio, se cita por referencia
para que ambos documentos no diverjan con el tiempo. Corregido tras bucle
adversarial (Seccion 6): la ruta real verificada de `agent_controller.py`
en este motor es `.agent/agent_controller.py` unicamente (nunca
`scripts/agent_controller.py`, que no existe):

```
scripts/prepush_check.py
.agent/agent_controller.py
bus/event_bus.py
bus/supervisor.py
.agent/closure_invariants.py
scripts/ensemble_dispatch.py
.agent/config/agents.json
```

**Verificacion de divergencia (bucle adversarial, Seccion 6):** antes de
aplicar esta lista en una sesion, si ha pasado mucho tiempo desde la ultima
revision de este documento, compara su contenido literal contra la Seccion
3.1 del documento canonico citado arriba -- si divergen, prevalece el
documento canonico y esta copia se declara desactualizada (nunca se asume
que la copia de aqui sigue vigente sin comprobarlo).

Si el bucle adversarial de este documento (Seccion 6) decide ampliar esta
lista para el proposito de seleccion de MODO (no solo para la cadencia de
revision S/M/L de las 4 capas), declararlo explicitamente aqui, nunca en
silencio.

### 4. Un ticket de la allowlist dentro de un lote grande NO fuerza todo el lote

Si el lote tiene 15+ tickets y solo 1-2 tocan la allowlist, el agente
propone **Intermedio** para la sesion completa, no Tradicional para el
lote entero -- forzar 15 tickets limpios a Tradicional solo porque 1 toca
un fichero critico desperdicia exactamente el ahorro de contexto que el
modo 4 capas/Intermedio existe para dar.

**Umbral de proporcion (bucle adversarial, segunda pasada, Seccion 6.1):**
si la allowlist cubre MAS del 20% de los tickets del lote (p.ej. 5 de 20),
el agente deja de proponer Intermedio por defecto y lo declara explicito
como zona gris -- a esa proporcion, la ventaja de contexto del modo
Intermedio frente a Tradicional completo deja de ser obvia y merece
pregunta directa, no un default automatico. Por debajo del 20%, Intermedio
sigue siendo el default sugerido de la señal 4 (Seccion 2).

---

## 5. Protocolo de cambio en caliente (`/agent-mode <modo>`)

Una sesion YA EN MARCHA en un modo puede cambiar a otro sin reiniciar la
conversacion. El trigger es el mismo que el de arranque (`/agent-mode
<tradicional|4capas|intermedio>`, o lenguaje natural equivalente -- ver
skill, Seccion de invocacion), pero el protocolo exige que el agente
declare, en ESTE ORDEN, antes de aplicar el cambio:

1. **Modo saliente y modo entrante**, nombrados explicitamente (nunca un
   cambio implicito que el usuario tenga que inferir del comportamiento).
2. **Definicion de "ronda en vuelo" (corregido tras bucle adversarial,
   Seccion 6 -- la version anterior solo hablaba de Capa 2).** Una "ronda
   en vuelo" es CUALQUIER invocacion de `ensemble_dispatch.py`/Kilo CLI ya
   lanzada y sin terminar al momento del cambio, de CUALQUIER capa (1
   Manager-nan, 1.5 Revisor-nan, o 2 Builder-nan) -- no solo Capa 2. Ninguna
   ronda en vuelo se aborta a mitad de ejecucion solo porque el modo
   cambio: cada una termina bajo el modo con el que arranco (acotada a la
   generacion de su salida actual, nunca a un proceso que se reinicie o se
   extienda). El modo nuevo aplica al SIGUIENTE ticket que se lance, y
   tambien a la SIGUIENTE capa de un ticket cuya capa anterior ya cerro
   pero cuya capa siguiente no se ha lanzado todavia (p.ej. Capa 1 de un
   ticket termino bajo el modo viejo, Capa 2 de ESE MISMO ticket se lanza
   ya bajo el modo nuevo si aplica). Excepcion: si el usuario pide
   explicitamente abortar el trabajo en vuelo, el agente lo hace y lo
   declara como tal (no como consecuencia automatica del cambio de modo).
   Caso sin siguiente ticket (el lote ya esta agotado cuando se pide el
   cambio): el agente lo declara explicitamente ("no queda ningun ticket al
   que aplicar el modo nuevo en este lote") en vez de fingir que el cambio
   tuvo efecto.
3. **Confirmacion de una sola pregunta** (mismo patron que la Seccion 2):
   el agente no cambia de modo por su cuenta ante una señal nueva a mitad de
   sesion -- PROPONE el cambio con su razon, el usuario confirma. Sujeto a
   la misma precedencia de la Seccion 2 (viabilidad y regla dura de
   seguridad por encima de la peticion explicita).
4. Tras el cambio, el agente actualiza el fichero de progreso vivo de la
   sesion si existe (p.ej. `PROGRESO_vuelo_limpieza_backlog_<fecha>.md`)
   con una linea que declare el cambio de modo y su razon. Si no existe
   ningun fichero de progreso vivo para esta sesion, el agente lo declara
   ("sin fichero de progreso que actualizar") en vez de omitir el paso en
   silencio -- no crea uno nuevo solo para este registro salvo que el
   usuario lo pida.

**Trazabilidad en modo Intermedio (bucle adversarial, segunda pasada,
Seccion 6.1):** un lote en Intermedio tiene el MODO DE SESION (Intermedio)
y, por ticket, una EJECUCION DIFERENCIADA (los de la allowlist van
integros por Claude Code; el resto por 4 capas completas). El fichero de
progreso (punto 4) declara, para cada ticket que cierra, CUAL de las dos
rutas siguio -- nunca basta con declarar el modo de sesion una sola vez al
principio, porque un lector posterior (otra sesion que herede el vuelo) no
podria distinguir que tickets paso por Claude Code directamente de los que
paso por Builder-nan sin releer cada commit.

---

## 6. Gobierno de esta propuesta (historico: como se congelo)

Este documento nacio `status: draft` y se sometio a un bucle adversarial
amplio antes de congelarse, proporcional al riesgo (afecta a como TODA
sesion futura de este motor decide su propio modo de trabajo -- riesgo
alto, Seccion 7 de `AGENTS.md`/del documento de 4 capas):

- **Codex** (lente sin filesystem o con filesystem segun disponibilidad).
- **GLM via opencode** (lente independiente, backend distinto a Codex y a
  los perfiles `nan`).
- **2 lentes `nan` CON filesystem** (via Kilo CLI, `channel: agent` +
  `backend: kilo`, modelos distintos entre si -- mismo principio de
  independencia de modelo que exige el propio modo 4 capas en su Seccion
  2.4) -- verifican que las 4 señales de la Seccion 2 son realmente
  verificables sin ambigüedad, y que el protocolo de cambio en caliente de
  la Seccion 5 no deja un estado inconsistente si se invoca a mitad de un
  lote.
- **Varios lentes SIN filesystem** (API, `channel: api`) -- revisan la
  coherencia textual del documento, si contradice algo ya fijado en
  `PROMPT_ARRANQUE_vuelo_limpieza_backlog_4capas_20261010.md` (nunca debe
  reabrir ni redefinir ese documento, solo generalizar su Seccion de modos
  a un concepto de sesion mas amplio), y si el criterio de "zona gris 4-14
  tickets" de la Seccion 2 es una heuristica razonable o arbitraria.

**Veredicto de cierre:** `frozen` solo si converge la MAYORIA ABSOLUTA de
lentes con contenido sustantivo (50%+1 del total de lentes independientes
que aportaron, nunca del total de lentes invocadas -- una lente muda o con
`no-aportacion` no cuenta en ningun lado de la fraccion; mismo umbral que
`check_loop_execution.py` exige para otros bucles de este motor); si hay
division real sobre un eje concreto, el usuario decide ESE eje antes de
congelar -- nunca el agente por su cuenta.

### 6.1 Resultado de la primera pasada (2026-10-10/11, informativo)

7 lentes independientes con contenido sustantivo (Codex/BA05,
GLM-opencode/BA06, 2 nan-con-FS via Kilo/BA08+BA09, nan/BA11, groq/BA30,
mistral/BA150; una octava lente, nvidia/BA21, tuvo contenido real en su log
pero el scorecard la registro como `no-aportacion` por fallo de transporte
-- no se cuenta formalmente, tratada como evidencia exploratoria). 6 de 7
convergieron en "no congelar todavia" (solo BA09 dio `frozen` sin cambios).
Correcciones ya aplicadas a este documento tras esa pasada: regla dura del
Intermedio (ninguna delegacion de Capa 1.5 en tickets de la allowlist, no
solo Capa 2), precedencia de señales con viabilidad/seguridad por encima de
la peticion explicita, fuente verificable para blast radius (señal 3),
umbral de 15 declarado como heuristica de amortizacion (nunca medicion
exacta) y sugerencia de default en zona gris mixta, definicion de "ronda en
vuelo" ampliada a las 3 capas en el protocolo de cambio en caliente (no
solo Capa 2), referencia canonica unica a `PROMPT_ARRANQUE_...` (nunca
`ARRANQUE_continuidad_...`) para la allowlist, y correccion de la ruta real
de `agent_controller.py`. Pendiente de una SEGUNDA pasada corta que
verifique estas correcciones antes de `frozen` definitivo.

### 6.2 Resultado de la segunda pasada (2026-10-11, informativo)

4 lentes independientes (Codex/BA05, nan-con-FS via Kilo/BA08, groq/BA30,
mistral/BA150), enfocadas en verificar punto por punto las 8 correcciones
de la Seccion 6.1. Convergencia fuerte: las 8 RESUELTAS (2 lentes marcaron
el punto 8 -- consistencia del hash -- como `NO VERIFICABLE desde texto`,
correcto por su parte; verificado DIRECTAMENTE por el orquestador con
`hashlib.sha256` sobre el fichero real: coincide con el declarado en la
skill). 3 hallazgos menores adicionales, ya corregidos: (a) umbral de
proporcion del 20% para cuando un lote "mixto" deja de tener a Intermedio
como default automatico (Seccion 4); (b) la fila de la tabla de modos
(Seccion 1) para "4 capas" aclarada para que no contradiga aparentemente
la Seccion 4; (c) trazabilidad por ticket en el fichero de progreso cuando
el modo de sesion es Intermedio (Seccion 5, punto 4); (d) aclaracion de
que protocolo aplica segun el momento de la peticion -- Seccion 2 completa
al arrancar, Seccion 5 a mitad de vuelo (Seccion 2, punto 1).

**Veredicto: `status: frozen`.** Ninguna lente de la segunda pasada senalo
un hueco bloqueante nuevo; los 3 hallazgos menores quedaron resueltos en
la misma sesion sin necesidad de una tercera pasada.
