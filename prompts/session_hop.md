# Prompt: Session Hop (arranque de sesion con continuidad medida)

> **Modo:** Solo lectura sobre el codigo y el estado operativo. Este prompt NUNCA muta
> `backlog.md`, `STATE.md`, `work_plan.md`, el bus ni codigo. Produce un ARRANQUE para
> pegar en una sesion nueva, y como mucho lo escribe en
> `<DESTINO_ROOT>/orchestrator_pipeline/arranques/`.
>
> Eres el PUENTE ENTRE SESIONES. Tu trabajo es que la sesion siguiente empiece con el
> METODO de la anterior y con el ESTADO **re-medido**, no recordado.

contract_id: cid-session-hop-v1
Skill canonica: skills/session-hop/SKILL.md
source_of_truth: este prompt. La skill `skills/session-hop/SKILL.md` es wrapper
operativo; si divergen, prevalece este prompt.

---

## La distincion que hace util a esta herramienta

Un arranque util transporta DOS cosas, y **mezclarlas es el defecto que este prompt
existe para evitar**:

| | Que es | Caduca | Como se trata |
|---|---|---|---|
| **METODO** | leer contratos enteros, medir antes de afirmar, no aceptar autoreportes, correr el bucle, lo que NO hacer | **No** | se HEREDA: vive aqui, versionado |
| **ESTADO** | SHAs, dirty, suite, buzon, commits sin publicar, que ticket bloquea a cual | **En horas** | se **RE-MIDE** al arrancar. **Jamas se copia** |

**Un ESTADO copiado se convierte en premisa falsa heredada.** Casos medidos en este repo,
todos en dos dias: un arranque declaraba un SHA de destino que ya no era el HEAD; decia
"237 pending" cuando eran 240 (y al dia siguiente 239); mandaba expandir 4 slugs de
memoria de los que **3 no existian** (`rc=1`); un censo dio `157 -> 152 -> 154`; y una
cifra de `15 de 16` era `14 de 16`.

*(Ni un solo SHA literal en este parrafo, a proposito: el test hermano
`test_el_prompt_no_cristaliza_estado` lo prohibe, y lo cazo al escribirlo. Un prompt que
predica no cristalizar estado no puede cristalizarlo.)*

> **Regla dura:** en el arranque que produzcas, **todo dato de estado va etiquetado como
> `[snapshot <fecha>]` y acompañado del comando que lo re-mide.** Un numero sin su
> comando es relato.

---

## Paso 0: ¿hay una mejora a ESTE prompt ya verificada por bucle, sin aplicar todavia?

Antes de recolectar nada, busca en
`<DESTINO_ROOT>/.agent/planning/PROPUESTA_mejoras_session_hop_*.md` (o el
patron equivalente si el arranque tambien va a citar
`orchestrator_launch_builder.md`). Si existe una con una seccion de "bucle
adversarial real corrido" y consenso `ADOPTAR`/`ADOPTAR CON CAMBIOS` para
algun hallazgo, **aplica esa mejora AL ARRANQUE QUE ESTAS PRODUCIENDO
AHORA**, aunque este prompt versionado todavia no la incluya — el arranque
es el vehiculo mas rapido para que la mejora llegue a la sesion siguiente,
sin esperar a que alguien edite y commitee este fichero primero. Decláralo
explicitamente en el arranque: "Este arranque incorpora la correccion <N>
de <ruta de la propuesta>, pendiente de aplicar a este prompt canonico."

Si la MISMA correccion se aplica manualmente en 2 o mas arranques
consecutivos, es momento de editar este prompt directamente — dejo de ser
una excepcion puntual y se volvio parte del metodo (mismo umbral que la
regla `prompt_override` de `orchestrator_session_close_full_audit.md`, ver
su Bloque 2.5.d, aplicado aqui con umbral mas bajo porque el volumen de
arranques reales es mucho menor que el de sesiones de trabajo).

## Paso 1: recolecta el ESTADO con el script, no de memoria

```bash
python <MOTOR_ROOT>/scripts/collect_session_state.py --project-root <DESTINO_ROOT>
```

**El script RECOLECTA; TU juzgas.** Emite hechos con `command:` + `exit_code:` y **nunca**
un veredicto. Si necesitas una conclusion (*"esto esta listo"*, *"esto bloquea"*), la
emites tu leyendo la evidencia — no la busques en su salida, porque por contrato no esta.

**Verifica el ARTEFACTO, no solo el exit code:** un `rc=0` significa "recolecte". Lee el
bloque que produjo.

**El script NO falla por un arbol sucio ni por una suite stale**: eso lo REPORTA. Un
`rc != 0` significa que fallo el propio recolector (ruta irresoluble, I/O), no que el
repo este mal.

## Paso 2: resuelve la TOPOLOGIA, no la asumas

El bloque del script trae los roles resueltos. **Contrastalos**: si el `motor_root` del
link apunta a un checkout distinto de aquel donde de verdad se commitea, el link esta
stale — no lo uses, reportalo.

Y **detecta el MODO**, nunca lo des por sabido:
`from runtime.project_root import is_motor_code_only`. Un vuelo reciente asumio
`code-only` y midio `False`: era MODO DESTINO, con otro pipeline gobernante.

**Si detectas drift entre el HEAD citado en un arranque previo y el HEAD real
(medido 2026-09-29 en 3 sesiones reales, siempre benigno: avance de linea por
trabajo paralelo, nunca ruptura), CLASIFICALO antes de reaccionar — no repitas
la recoleccion completa por cualquier discrepancia, eso convertiria el caso
normal en ceremonia de cada lanzamiento:**

1. **Avance en linea** (`git merge-base --is-ancestor <HEAD-citado>
   <HEAD-actual>` da exit 0): drift benigno, el caso normal de trabajo
   paralelo. Re-mide SOLO los campos afectados por ese avance (el propio
   HEAD, y si la suite citada corresponde a ese commit) — no repitas la
   recoleccion completa. Decláralo como nota, no como alarma.
2. **Ruptura de linaje** (el comando anterior da exit distinto de 0: el
   commit citado ya NO es ancestro): esto SI invalida el arranque. Detente
   y reportalo como hallazgo explicito antes de continuar — no sigas
   usando ningun dato del arranque original.
3. **Suite citada ya no corresponde al HEAD actual** (con o sin ruptura de
   linaje): el dato de "suite verde" queda invalidado puntualmente, aunque
   el resto del arranque siga siendo valido — decláralo asi, sin invalidar
   todo el arranque por un solo campo obsoleto.

## Paso 3: nombra los CONTRATOS que gobiernan la sesion siguiente

Por cada contrato: **ruta absoluta y numero de lineas**. La regla M4 exige leerlos
ENTEROS antes de producir nada que se mida contra ellos; `grep` y `diff` **no cuentan**:
son muestreo, y el muestreo no ve lo que OMITES.

Si el arranque va a ordenar un fan-out, **el contrato viaja por CONTENIDO en el bundle,
nunca por ruta**: una lente ciega solo puede auditar coherencia interna.

**Por cada contrato citado con `contract_sha256` en el arranque que produces,
instruye explicitamente a la sesion siguiente a verificar SU hash, no solo el
de `orchestrator_launch_builder.md`** (cuyo Paso -1 solo se nombra a si mismo
por diseno: es el contrato que se esta ejecutando). Generaliza la tabla de
identidad a "TODO contrato con hash declarado en este arranque se verifica
antes de usarse" — medido 2026-09-29, 2 de 3 sesiones reales verificaron solo
el hash que el Paso -1 nombraba, dejando sin comprobar el resto. **Matiz de
accesibilidad:** si el contrato con hash declarado no esta accesible en el
entorno de la sesion que ejecuta, no falles en falso ni asumas coincidencia —
instruye "verificalo si es accesible; si no, decláralo pendiente de
verificacion".

## Paso 4: verifica los slugs de memoria ANTES de citarlos

```bash
python <MOTOR_ROOT>/scripts/memory_context.py --recall --id obs-<slug>
```

**Cita SOLO los que devuelven `rc=0`.** Un arranque que ordena expandir un slug
inexistente le regala al ejecutor un paso que no puede cumplir — y si ademas el prompt
avisa de "slugs que no existen" mientras cita otros que tampoco, el arranque se
contradice.

**Incluye una STOP CONDITION explicita:** si un `--recall --id` ordenado da `rc=1`, el
ejecutor **NO sigue como si hubiera cumplido el paso**: lo registra como hallazgo.

## Paso 5: transporta los AVISOS MEDIDOS, no los genericos

Un aviso vale si tiene medicion detras. Los que este repo tiene medidos y suelen aplicar:

- **Mudez de lentes:** accesible **no** es round-trip. Una respuesta truncada **no es un
  veredicto: es una lente MUDA**. Y una lente sin filesystem puede **fabricar** evidencia
  (medido: declaro BLOCKER sobre ficheros de 338, 1761 y 117 lineas diciendo que no
  existian).
- **`privacy_preflight`:** un slug de >=39 chars con guiones se clasifica "token opaco de
  alta entropia" (umbral 4.0 bits/char) y **bloquea el envio**. **Acorta el nombre; no
  relajes el guard.**
- **Line endings:** no MEZCLES vias de escritura en un fichero. `Write`/`Edit` deja CRLF;
  `cat >>`/`printf` deja LF. Mezclarlas aborta el commit.
- **Orden de trabajo:** la suite canonica va la **ULTIMA**. Cualquier commit posterior la
  invalida (`tested_commit_sha == HEAD`).
- **Cifra de un documento de diseño != cifra real de filesystem** (medido
  2026-09-29): una cifra citada de un documento de diseño sobre una superficie
  con **crecimiento sin control declarado** (rotacion pendiente, cola sin
  limite, "restos de sesiones anteriores") puede estar desactualizada sin que
  ninguna auditoria de TEXTO lo detecte — 3 rondas adversariales sobre un
  arranque no cazaron que "3-4 JSONL sin cubrir" eran en realidad 120 ficheros
  sueltos; solo lo caza quien ejecuta el censo real (`find`/`Get-ChildItem`)
  contra el disco. Si vas a citar una cifra asi, ejecuta el comando de censo
  real ANTES de transportarla, y etiqueta la cifra del documento como
  `[cifra de diseño, no re-verificada desde <fecha>]` si decides no re-medir.
  **El comando exacto usado importa tanto como el resultado**: una medicion de
  filesystem tambien puede ser inexacta (mal contada, mal filtrada) — cita
  siempre el comando, no solo la cifra.
- **Hallazgo NUEVO de tipo MEDICION lleva el mismo contrato de evidencia que
  el Paso 1 exige al script**: si la sesion arrancada descubre por su cuenta
  una cifra, un conteo, o la existencia/ausencia de un artefacto (no
  transportado del arranque), su reporte lleva `command:` + `exit_code:`
  explicitos, igual que el estado recolectado. Un hallazgo de este tipo sin
  su comando de reproduccion es una afirmacion, no una medicion. Un hallazgo
  de tipo INTERPRETACION (un juicio, una hipotesis, una lectura de intencion)
  no necesita este formato, pero decláralo explicitamente como interpretacion
  para que no se confunda con una medicion verificada.

## Paso 6: escribe LO QUE NO HACER

Es la seccion que mas evita incidentes. Deriva del rol de la sesion siguiente: si es de
DISENO, su zona prohibida; si es de VUELO, los tickets `DISENO_PRIMERO`/`REQUIERE_HUMANO`
que no debe ejecutar y las superficies que colisionan con otra sesion en curso.

## Paso 7: el sello, si aplica

Si la sesion siguiente es un vuelo autonomo, necesita
`start_context_isolation.json` con `flight`, `prompt_sha256` y `approved_by` **externo**.
Recuerda dos cosas medidas:

- **Sella el ULTIMO.** El `prompt_sha256` ata el recibo a los bytes exactos: cualquier
  edicion posterior lo invalida. Audita y corrige el arranque **antes** de sellar, o
  gastaras la aprobacion del operador dos veces sobre el mismo artefacto.
- **Sin BOM.** Un BOM hace que `json.load` reviente en la linea 1 antes de leer un campo.

---

## Salida

Un unico bloque markdown pegable como PRIMER mensaje de la sesion nueva, con:

1. Contratos que gobiernan (ruta absoluta + lineas)
2. Topologia resuelta y **medida**, con su comando de re-medicion
3. Estado `[snapshot <fecha>]`, cada dato con `command:` + `exit_code:`
4. Slugs de memoria **verificados `rc=0`** + STOP CONDITION
5. Avisos medidos que apliquen
6. **Lo que NO hacer**
7. Sello, si aplica

Opcionalmente escrito en
`<DESTINO_ROOT>/orchestrator_pipeline/arranques/ARRANQUE_<slug-corto>.md`.
**Slug corto** (ver Paso 5).

## Restriccion dura

- **NO** cristaliza estado en ningun fichero versionado del motor. Ni un SHA.
- **NO** muta `backlog.md`, `STATE.md`, `work_plan.md`, el bus ni codigo.
- **NO** ejecuta el trabajo de la sesion siguiente: lo prepara.
- **NO** sustituye a `orchestrator_session_bootstrap*.md` (definen el ROL; este
  transporta la CONTINUIDAD) ni a `/pause-work`, `/resume-work`, `/session-report` (leen
  el estado operativo de UN ticket).
- **NO** emite veredictos en el bloque de estado: los hechos son del script, el juicio es
  del agente.
