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

## Paso 3: nombra los CONTRATOS que gobiernan la sesion siguiente

Por cada contrato: **ruta absoluta y numero de lineas**. La regla M4 exige leerlos
ENTEROS antes de producir nada que se mida contra ellos; `grep` y `diff` **no cuentan**:
son muestreo, y el muestreo no ve lo que OMITES.

Si el arranque va a ordenar un fan-out, **el contrato viaja por CONTENIDO en el bundle,
nunca por ruta**: una lente ciega solo puede auditar coherencia interna.

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
