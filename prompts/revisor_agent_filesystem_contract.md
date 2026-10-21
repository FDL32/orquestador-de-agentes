# Contrato: Revisor con filesystem completo (modo 3 de invocacion del Revisor)

contract_id: cid-revisor-agent-fs-v1
nucleo_referenciado:
  - prompts/ensemble_loop.md (contract_id cid-ensemble-loop-v1, §3.3 "Preparar el bundle")
  - prompts/revisor_independent_review.md (contract_id cid-revisor-review-v1, §2 "Veredicto")
  - prompts/builder_invocation_contract.md (contract_id cid-builder-invocation-v1, §1 "Como invocar un Builder real via Kilo CLI")

source_of_truth: este prompt para el modo 3 de invocacion del Revisor. Si diverge
de los prompts nucleares, cada uno prevalece en su propio alcance (regla X-09).

## 0. Alcance: cuando usar este modo

Usa este modo SOLO si la tarea de revision exige leer el repo completo sin bundle
acotado. Para bundles cortos (menos de 15 KB), usa siempre `ensemble_dispatch.py
loop-round` (regla dura, aplica a cualquier modelo en rol Revisor, no solo a los
de `nan`).

Este modo no tiene bus ni pasa por `ensemble_dispatch.py`/`filter_lens_output.py`
automaticamente. Es un encargo directo al agente via Kilo CLI (canal `agent` de
`builder_invocation_contract.md` §1), pero el agente aplica la disciplina de
`revisor_independent_review.md` (§2) y los marcadores de `ensemble_loop.md` §3.3
(sus propios marcadores).

## 1. Marcadores de bundle adaptados (de `ensemble_loop.md` §3.3, sin limite de 15 KB)

1. Tres marcadores obligatorios: `INVENTARIO DE EVIDENCIA`; un presupuesto de
   exploracion (`PRESUPUESTO`, "no mas de ..."); y la instruccion de responder
   `NO VERIFICABLE` (literal, con espacio) en vez de afirmar lo que no puede
   comprobar.
2. Declara `CANAL: agent` explicitamente.
3. Declara `ROL DE LA LENTE: REVISOR/AUDITOR`.
4. `repo_scope: destino` con rutas absolutas. Dado que este modo lee el repo real,
   NO limita el bundle a 15 KB: el limite de `ensemble_loop.md` §3.3 punto 4
   no aplica aqui.
5. Si generas el prompt de arranque con un heredoc de Bash, pon el delimitador
   entre comillas simples (como `ensemble_loop.md` §3.3 punto 5).

## 2. Formato de veredicto y disciplina (por CITA, no redeclaracion -- regla X-09)

Usa EXACTAMENTE el formato de veredicto, la tabla de evidencia proporcional a
`deliverable_type` y la disciplina anti-confirmacion de `prompts/revisor_independent_review.md`
§2 y §4.5. Este contrato no reproduce ese contenido aqui: si lo citaras de memoria en vez de
leerlo, corres el riesgo de desincronizarte en la siguiente correccion de ese prompt (es
precisamente el anti-patron que esos mismos parrafos de §4.5 citan de AGENTS.md,
WOT-2026-024u). Lee `revisor_independent_review.md` §2 y §4.5 ENTEROS antes de emitir tu
veredicto.

## 3. Verificacion de forma de veredicto (sin filter_lens_output.py)

Este modo NO pasa por `filter_lens_output.py` automaticamente. El prompt de
arranque debe pedirle al propio agente que aplique la logica equivalente:

- Antes de escribir su veredicto a fichero, que verifique la forma de su propio
  veredicto con `python scripts/filter_lens_output.py --lens-output <f> --root <repo>`
  (CLI standalone, no necesita import de Python).
- Si el resultado indica `confirmation_no_objection`, el agente re-clasifica
  internamente su veredicto como CHANGES y re-encola.

Esto reemplaza la barrera mecanica de `filter_lens_output.py` que `loop-round`
aplica automaticamente en `ensemble_dispatch.py`.

## 4. Invocacion (canal de `builder_invocation_contract.md` §1)

Invocacion canonica via Kilo CLI (canal `agent`):

    kilo run \
      --auto \
      -m nan/<modelo> \
      --dir "<ruta-absoluta-al-repo-destino>" \
      --format json \
      --print-logs \
      -f "<ruta-absoluta-al-prompt-de-instrucciones>" \
      -- \
      "<mensaje corto que remite al fichero adjunto>" \
      > <ruta-log> 2>&1 &

El prompt de instrucciones debe ser ESTE fichero (o un prompt que lo incluya).

**Advertencia de backgrounding doble (medida en WOT-2026-106a, no cosmetica):** el `&` final
de este comando asume que lo lanzas desde una terminal normal con UN solo nivel de
backgrounding. Si lo invocas desde un orquestador que YA pone este comando dentro de su
propio mecanismo de `run_in_background`, los dos niveles se desacoplan: el proceso `kilo.exe`
sigue vivo mucho despues de que el wrapper exterior reporte "completado", y si relanzas
sobre la MISMA sesion (`-s <id>`) antes de que el anterior termine, dos procesos escriben
sobre los mismos ficheros a la vez (corrupcion medida: secciones duplicadas 3-4 veces).
Antes de confiar en una notificacion de "completado": verifica con
`Get-CimInstance Win32_Process -Filter "Name='kilo.exe'"` (Windows) que el proceso real ya
no esta vivo, o quita el `&` interno si el mecanismo de backgrounding del orquestador ya lo
provee.

## 5. Recibo de lecturas

A diferencia de `loop-round`, aqui no hay un mecanismo de recibo de lectura
automatico. El prompt de arranque debe pedir explicitamente al agente que cite
`ruta:linea` de cada verificacion que haga, y que declare cuales ficheros no
pudo leer (si los hubo).

## 6. Relacion con `ensemble_loop.md` y `revisor_independent_review.md`

Este modo NO redefine lo que `ensemble_loop.md` §3.3 y `revisor_independent_review.md` §2
ya definen. Hereda por referencia las reglas de marcadores, veredicto y disciplina. Este
modo 3 es EXCLUSIVAMENTE la invocacion directa de Kilo CLI como agente (Seccion 4), sin
`ensemble_dispatch.py loop-round`: si la tarea cupiera en un bundle acotado y pudiera ir por
`loop-round`, no uses este modo 3 en absoluto -- usa `loop-round` (regla de la Seccion 0).
No existe una variante hibrida "modo 3 despachado por loop-round"; si alguna vez se necesita
esa combinacion, es un modo 4 nuevo que se documenta por separado, nunca una excepcion
silenciosa de este.
