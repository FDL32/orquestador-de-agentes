# DEC-040I-001: Que pasa con la fila del scorecard cuando falta el challenge_nonce

**Ticket:** WOT-2026-040i (en review; bloqueado por esta decision)
**Ticket en conflicto:** WOT-2026-048i (completed, su contrato sigue vivo)
**Fecha:** 2026-09-18
**Estado:** PROPUESTA -- pendiente de decision del Usuario
**Autor:** Agente (Manager review). **El agente propone, no decide** (NG-RAIZ).

## Por que esto es una DEC y no un fix

`repo_charter.md:25-29` (**NG-RAIZ**) es literal:

> Cuando falta un contrato (`repo_charter`, `destination_root`, `ticket_prefix`, una
> `DEC-*` necesaria), el motor **falla explicito o pide `DEC`**. No inventa destino, ni
> superficie distribuible, ni reglas de adopcion. Es la raiz de la que salen los demas
> Non-Goals, y el antipatron que mas ha costado: **inventar una premisa en vez de medirla
> o pedir la decision.**

Dos contratos congelados piden cosas incompatibles sobre la MISMA celda de estado.
Cualquier arreglo en codigo -- mover el check, tocar el test del otro ticket, anadir una
excepcion -- es el motor decidiendo politica por heuristica. Por eso se para y se pide
`DEC`.

## El conflicto, medido

Ambos contratos son correctos POR SEPARADO y ambos tienen evidencia detras.

| Contrato | Exige | Razon documentada en su propio artefacto |
|---|---|---|
| `WOT-2026-048i` | error de USO -> **1 fila** con `failure_mode` | sin ella, *"nadie consulto a esta lente"* y *"la lente no llego a responder"* son INDISTINGUIBLES en el scorecard |
| `WOT-2026-040i` | fase de gobierno sin nonce -> **0 filas** (criterio 2) | no gastar la ronda; el fallo debe preceder a la llamada al backend |

**Interseccion en conflicto:** fase de gobierno + nonce ausente + error de uso.
Pide 1 fila y 0 filas a la vez.

### Evidencia (ruta productiva, no test)

Probe real contra `scripts/ensemble_dispatch.py`, midiendo el scorecard antes/despues:

```
version STAGED  · fase gobierno SIN nonce + task_type invalido -> rc=1, scorecard delta=+1
version aa21d63 · mismo caso                                    -> rc=1, scorecard delta=0
```

Y el test de `048i` en el arbol actual (con el trabajo staged aplicado):

```
FAILED tests/unit/test_ensemble_dispatch.py::test_loop_round_usage_error_leaves_auditable_row
  -> 1 failed, 169 passed
```

Ese test invoca `--phase CONTRACT_AUDIT` **sin** `--challenge-nonce` y asevera
`len(rows) == 1` con `row["failure_mode"] == "usage-error"`.

**Precision exigida por el bucle L1130 (BA11), y la correccion es justa:** la version
anterior decia *"no es un test que estorbe: es el contrato de 048i ejercitandose"* junto al
Probe 4 que lo muestra en `FAILED`. Las dos cosas son ciertas pero la frase inducia a leer
el rojo como benigno. Preciso: **el test esta ROJO** (`FAILED`, Probe 4) con el trabajo
staged aplicado; lo que la DEC sostiene es que ese rojo **no se arregla tocando el test**,
porque lo que falla es la interseccion de dos contratos, no la aseveracion del test. Rojo
real, causa ajena al test.

## Origen del hueco (para no repetirlo)

`WOT-2026-048i` es ANTERIOR. Su contrato no podia prever a `040i`. Pero `040i` **redacto
su criterio 2 sin censar que contratos ya gobernaban el scorecard**: su DoD exigia un
censo de call-sites (*quien llama a `loop-round`*), no un censo de CONTRATOS sobre la
superficie que iba a tocar. Por eso el choque aparecio en review y no en Contract
Formation. Ese hueco se ficha aparte (ver "Deuda asociada").

## Opciones

No son equivalentes. La diferencia es QUE PROPIEDAD MEDIDA se pierde.

### (a) `048i` cede: su contrato se acota a fases NO de gobierno

- **Coste:** se pierde observabilidad justo donde mas importa. Un error de uso en una fase
  de gobierno deja de ser auditable, y el bucle 1->9->2 es precisamente donde hace falta
  distinguir "no se consulto" de "no respondio".
- **Requiere:** editar el test de `048i` y declarar la reduccion de alcance en su ficha.
- **Riesgo:** reabre el fallo que `048i` cerro, en el subconjunto mas critico.

### (b) `040i` cede: admite fila con `failure_mode: missing-nonce` (RECOMENDADA)

- **La tension resulta ser APARENTE.** `040i` escribio "0 filas" cuando lo que le importaba
  era **0 llamadas al backend**. Son cosas distintas y su criterio 2 las confundio: la
  fila NO cuesta una ronda; la llamada si.
- **Satisface a los dos:** hay fila (lo que `048i` exige para poder auditar) y no hay
  llamada al backend (el coste real que `040i` queria evitar).
- **Requiere:** reformular el criterio 2 de `040i` como *"0 llamadas al backend y la fila
  registra `failure_mode: missing-nonce`"*, y anadir el caso cruzado a sus tests.
- **Coste:** el contrato de `040i` ya esta frozen -> exige la via de `CONTRACT_GAP`
  (`contract_formation_pipeline.md`), no una edicion en caliente.

### (c) Reordenar el check sin mas -- **DESCARTADA, no es opcion**

Es lo que hace el trabajo staged actual. **Medida y refutada:** rompe el criterio 2 de
`040i` (`delta=+1` con nonce ausente). No resuelve el conflicto, lo mueve de sitio.

### (d) Clasificar el fallo: ninguno de los dos contratos cede

**Anadida tras el bucle adversarial L1130.** La propusieron DOS lentes independientes
(BA05 y BA11) y la version anterior de esta DEC la OMITIA, presentando (a)/(b)/(c) como el
espacio completo. No lo era.

`failure_mode` **ya existe** en el schema del scorecard y **ya distingue clases**
(`VERIFICADO EN CODIGO`: `ensemble_dispatch.py` lo emite con `usage-error` en `:2714`,
`transport_failed` en `:2010`, `discarded_reason` en `:2338`, y figura en la lista de
campos de `:144`). Luego el instrumento para separar los dos casos ya esta construido:

- `failure_mode: "usage-error"` -> lo que `048i` exige auditar (hubo intento de uso real)
- `failure_mode: "missing-nonce"` -> clase NUEVA y distinta: la ronda no llego a intentarse

Cada contrato se satisface sobre SU clase, sin que ninguno reduzca alcance ni reformule su
criterio. Es (b) llevada a su forma precisa, y probablemente la salida correcta.

**Lo que (d) exige y aun NO esta medido:** que ningun consumidor del scorecard cuente filas
sin filtrar por `failure_mode` (`check_loop_execution`, `adjudicate`, `leaders`, cualquier
metrica). Si alguno lo hace, una clase nueva le cambia el denominador en silencio. **Ese
censo es condicion previa a elegir (d)** y no se ha hecho.

## Recomendacion del agente

**(d)**, que sustituye a la recomendacion anterior -- (b) -- tras el bucle L1130.

Motivo del cambio: (b) pedia a `040i` reformular su criterio 2, es decir, que un contrato
cediera. (d) no pide ceder a ninguno, porque el campo que los separa YA EXISTE. Es
estrictamente menos destructiva y usa un mecanismo del sistema en vez de inventar politica.

Orden de preferencia: **(d) > (b) > (a)**; (c) refutada.

**Condicion previa a (d):** censar los consumidores del scorecard (arriba). Si el censo
encuentra un consumidor que cuenta sin filtrar, (d) arrastra ese arreglo y hay que decidir
si entra en `040i` o sale como ficha.

La decision es del Usuario: es politica de producto (que garantiza el scorecard), no de
implementacion, y `NG-RAIZ` prohibe que la tome el motor.

## Consecuencias por opcion

| | `048i` | `040i` | Trabajo staged | Via |
|---|---|---|---|---|
| (a) | alcance reducido, test editado | intacto | sirve casi entero | ficha de reduccion de alcance |
| (b) | intacto | criterio 2 reformulado | exige el caso cruzado nuevo | `CONTRACT_GAP` sobre contrato frozen |
| (c) | roto | roto | tal cual | -- |

## Deuda asociada

El censo que `040i` no hizo -- **enumerar los contratos vivos que gobiernan una superficie
antes de congelar uno nuevo sobre ella** -- se ficha como `WOT-2026-070p`. Esta DEC
resuelve ESTE choque; aquella ficha evita el siguiente.

## Estado de bloqueo

Mientras esta DEC siga en `PROPUESTA`:

- `WOT-2026-040i` queda en `CHANGES` y **no se cierra**.
- El trabajo staged **no se commitea**: su forma depende de la opcion elegida.
- `aa21d63` queda publicado y con 12 tests rojos en CI. **No se revierte** (el trabajo
  staged lo arregla casi entero; revertir obligaria a rehacerlo).
