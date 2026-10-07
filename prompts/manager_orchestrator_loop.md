---
role: orchestrator
cycle_phase: [F1-backlog, F2-contrato, F3-auditoria-contrato, F4-lanzamiento, F5-implementacion, F6-revision]
route_kind: modo
---
# Nucleo portable del proceso Manager-Builder con bucles F/S
<!-- PROMPT-SUMMARY
what: Nucleo portable del proceso Manager-Builder: roles, contrato de capacidades, reglas de validez de un bucle (F/S), maquina de estados, plantillas por canal, esquemas ejecutables y metricas de mejora continua.
when: Cuando un Manager orquesta un objetivo con bucles de revision adversarial sobre una estrategia, sobre cada plan y sobre el prompt del ejecutor, en CUALQUIER sistema (no solo este repositorio).
not: NO sirve para despachar lentes contra un proveedor concreto ni para encargar una tarea a un backend: eso vive en `prompts/ensemble_loop.md` y `prompts/builder_invocation_contract.md`, que el ADAPTADOR traduce a cada sistema.
-->

contract_id: cid-manager-orchestrator-loop-v1
Skill canonica: skills/manager-orchestrator-loop/SKILL.md

## 0. Que es y como se usa

Este documento es el NUCLEO del proceso Manager-Builder. Es una especificacion ejecutable y
GENERAL: no conoce ningun repositorio, ningun proveedor, ningun lenguaje ni ninguna herramienta
concretos. Solo el nucleo gobierna. Alrededor de el:

- un ADAPTADOR por sistema traduce cada capacidad (leer ficheros, ejecutar, registrar, ...) a los
  comandos reales de ese sistema;
- un PERFIL declara, por capacidad, que la cubre, su version, una prueba de vida y el nivel
  degradado elegido; el preflight lo valida contra el esquema antes de lanzar nada;
- una SKILL y una PROYECCION de usuario lo apuntan con su `contract_id` y su hash, sin re-declarar
  criterios ("skill apunta, prompt gobierna").

Reglas de la skill y la proyeccion (portables): la skill SOLO apunta (`contract_id`, ruta y hash) y
tiene prohibido re-declarar criterios; la proyeccion es una COPIA generada con version y hash, nunca
se edita a mano; la comprobacion del hash corre AL INVOCAR (no solo en un sistema de integracion
continua): si el nucleo alcanzable tiene otro hash, se imprimen los dos y no se sigue, y si no hay
nucleo alcanzable ni copia, no se sigue y se declara. Cuando cambia el nucleo, se regenera la
proyeccion. (b)

Tres formas de uso, de menos a mas: (1) pegar este nucleo como prompt de arranque del Manager y
rellenar el perfil a mano; (2) cargarlo desde una skill que lo apunta con su hash; (3) una
herramienta del sistema que hace el preflight, prepara los bundles por canal, lanza, fotografia y
registra.

Los niveles (a)/(b)/(c) remiten a los casos de la propuesta de diseno de origen; el nucleo no los
reproduce. Origen: propuesta v3 del proceso Manager-Builder (sha256
`f2eb3e3a2ade460c79c19a02f5cb3a5d123504259c823c0292c12cd9d5bec218`).

## 1. Vocabulario

| Termino | Que es |
|---|---|
| lente | un modelo que opina sobre un objeto y CUENTA como voto si su identidad y su ronda son validas |
| identidad | el par (proveedor, modelo). Dos claves internas distintas pueden ser la MISMA identidad y una misma clave puede haberse usado con modelos distintos: la clave NO es identidad |
| canal | FICHEROS (la lente puede leer el arbol) o TEXTO (la lente no tiene acceso a ficheros) |
| bundle | el material que se entrega a una lente, preparado POR CANAL |
| recibo de lectura | evidencia de que una lente con bundle de FICHEROS realmente leyo (llamadas a herramientas de lectura en su log) |
| ronda | la ejecucion de una lente sobre un objeto, con su ancla (objeto revisado) |
| ronda muda | una ronda sin respuesta sustantiva; no cuenta |
| sustitucion | una lente distinta de la pedida que responde en su lugar; se declara y puede no contar |
| verificador de hechos | el rol que comprueba hechos y NUNCA cuenta como lente |
| adjudicacion | el registro por ronda que decide que se adopta y por que |
| insuficiente | el veredicto cuando no se alcanzan los minimos; nunca se simula |
| escalado | la via para llevar al USUARIO las dos posturas cuando el bucle no converge |

### 1.1 Los dos bucles

- **Bucle F** (lente con ficheros): el bundle es de FICHEROS. La lente puede leer el arbol y sus
  hechos se cierran con citas verificables. Una lente de un bucle F es EFECTIVA solo si hay recibo
  de lectura y su salida cita referencias comprobables (ver seccion 4). (a)
- **Bucle S** (lente sin ficheros): el bundle es de TEXTO. Sobre HECHOS una lente sin ficheros solo
  puede responder NO VERIFICABLE; una confirmacion suya se descarta. Sus hallazgos de diseno y de
  preferencia si cuentan. (a)

Una lente lanzada con bundle de FICHEROS que responde sin leer NO es una lente F: cuenta como lente
sin ficheros y se declara. (a) Una lente lanzada con bundle de TEXTO nunca se reclasifica. (a)

### 1.2 Niveles de evidencia

Cada regla de este nucleo declara su nivel de evidencia, y quien la cita lo conserva:

- **(a)**: observada en dos o mas casos o rondas independientes (la mas fuerte).
- **(b)**: observada en un unico caso.
- **(c)**: hipotesis, pendiente de confirmar.

## 2. Roles

- **MANAGER**: orquesta, divide, lanza y adjudica con comando. Nunca cuenta como lente.
- **EJECUTOR** (Builder): implementa. Su informe no es evidencia; lo son el diff y el artefacto.
- **LENTE**: opina y CUENTA. Su identidad (proveedor, modelo) debe ser distinta de la del autor del
  objeto y de las demas lentes contadas. (a)
- **VERIFICADOR DE HECHOS**: de cualquier familia, incluido el mismo motor que el Manager. Solo
  devuelve hechos con cita o con comando y su salida. NUNCA cuenta. Recibe todo NO VERIFICABLE y
  toda preferencia apoyada en uno antes de contar votos. Tiene presupuesto propio (lecturas y
  tiempo). No escribe una fila de ronda, asi que el comprobador de validez no tiene nada que contar:
  que nunca cuente lo garantiza el canal, no una norma. (b)
- **USUARIO**: decide criterio, politica y producto; recibe los escalados.

## 3. Contrato de capacidades

Toda capacidad que ejecuta un comando externo lo hace con entorno minimo (sin credenciales de otros
proveedores) y con limite de tiempo. El perfil declara, por capacidad, su comando, su version, una
prueba de vida y el nivel degradado elegido.

| Capacidad | Entrada -> salida minima | Si falta (nivel degradado) |
|---|---|---|
| LECTOR_FS | tarea "verifica X en <ruta>" + rutas absolutas -> hechos con cita o comando y salida, escritos a fichero | sin verificador no hay bucle de GOBIERNO, solo EXPLORATORIO |
| LENTE_TEXTO | bundle autocontenido con el contrato por contenido -> hallazgos + NO VERIFICABLE + decision | el bucle sigue con lectores; se declara |
| EJECUTOR | prompt con criterio de hecho -> diff + artefacto + log | modo implementador=manager (seccion 9) |
| EVIDENCIA | foto antes/despues (hash del arbol o del diff), commit o revert | sin VCS: hash por fichero de las rutas declaradas |
| REGISTRO_TRABAJO | alta, estado, cierre con evidencia | una tabla versionada |
| REGISTRO_RONDAS | por ronda: lente PEDIDA y la que RESPONDIO, identidad, sustituciones, tamanos, salida | un JSONL local |
| BARRERAS | gates obligatorios por tipo de entrega | se declaran los que faltan; ningun cierre los da por pasados |
| CANAL_SESIONES | reclamo de tarea y peticiones entre sesiones | el USUARIO hace de bus (riesgo declarado) |
| DECISIONES | registro de decisiones del USUARIO | un fichero por ciclo |
| IDENTIDAD | registro unico de lentes: clave -> (proveedor, modelo) | el lanzador anota proveedor y modelo de cada respuesta |
| ESCALADO | canal para llevar al USUARIO las dos posturas cuando el bucle no converge | se para el ciclo y se declara |

Toda capacidad con esquema puede declararse como "tabla versionada" o "JSONL local": ese es el
NIVEL MINIMO, no un escape de la validacion.

## 4. Reglas de validez de un bucle

1. Cuenta IDENTIDADES (proveedor, modelo) distintas, no claves. El ADAPTADOR declara como cuenta su
   barrera hoy (si cuenta claves) y como cierra esa diferencia; hasta entonces el Manager coteja
   clave a modelo a mano. (a)
2. No cuentan: el autor del objeto, el emisor del ancla, una sustitucion por el modelo del Manager
   ni una ronda muda. Un refuter (la lente final con ficheros) cuenta como cualquier lente si su
   ronda es sustantiva: la exclusion por rol es un error de contrato, no una regla. (a)
3. Una lente lanzada con bundle de FICHEROS es EFECTIVA si hay RECIBO DE LECTURA del lanzador
   (llamadas a herramientas de lectura en el log) Y su salida cita referencias `ruta:linea`
   comprobables: el Manager o la herramienta cotejan una muestra (la linea citada contiene lo que la
   lente dice) y un comando solo vale si es de solo lectura, reproducible y trae su salida. Citar no
   basta: una cita sin lectura no es una cita verificada. Si responde sin leer, cuenta como lente
   sin ficheros y se declara. La latencia es una senal barata, no la prueba. (a)
4. MINIMOS POR TIPO DE ENTREGA: son un PARAMETRO del ADAPTADOR, no numeros fijos del nucleo. El
   perfil declara, por tipo de entrega, cuantas lentes independientes y cuantos verificadores se
   exigen. Todo bucle de GOBIERNO exige al menos los verificadores que el perfil declare para su
   tipo; sin verificador no hay bucle de gobierno, solo EXPLORATORIO. (a)
5. El ancla de la ronda contiene el objeto revisado, y el asunto de la ronda coincide con el del
   ancla. (b)
6. Si no se llega al minimo: INSUFICIENTE. Nunca se simula. (a)
7. **N8 - un commit, un bucle anclado**: los hallazgos ADOPTADOS de un mismo bucle se aplican en
   UN solo commit, y ese commit lleva anclado UN bucle de verificacion (una ronda cuyo ancla ES
   ese commit, no el objeto original). No se aplica un commit por hallazgo ni se da por cerrado
   un bucle cuyos cambios quedaron repartidos en varios commits sin ancla. La suite va al final,
   despues del ultimo commit. (b)

## 5. Estados y mapeo de las once fases

Maquina de estados:

OBJETIVO -> ANALISIS -> ESTRATEGIA -> [BUCLE_ESTRATEGIA] -> DIVISION -> [BUCLE_PLAN] -> por plan:
PROMPT_EJECUTOR -> [BUCLE_PROMPT_EJECUTOR] -> EJECUCION -> REVISION -> CIERRE -> MEJORA -> siguiente
plan. Cada estado tiene criterio de entrada, artefacto de salida y barrera. Desde cualquier bucle,
NO_CONVERGE -> ESCALADO.

Este nucleo mapea las ONCE FASES del patron del usuario a esos estados 1:1:

| # | Fase del patron | Estado(s) del nucleo |
|---|---|---|
| 1 | objetivo | OBJETIVO |
| 2 | analisis | ANALISIS |
| 3 | estrategia | ESTRATEGIA |
| 4 | bucle sobre la estrategia | BUCLE_ESTRATEGIA |
| 5 | division en planes | DIVISION |
| 6 | bucle sobre cada plan | BUCLE_PLAN |
| 7 | implantacion por riesgo ascendente | PROMPT_EJECUTOR (orden por riesgo, del mas simple al mas complejo) |
| 8 | bucle sobre el prompt del ejecutor | BUCLE_PROMPT_EJECUTOR |
| 9 | ejecucion y revision por un modelo distinto | EJECUCION -> REVISION |
| 10 | mejora continua medible | MEJORA (metricas, seccion 8) |
| 11 | limites de autoridad | ESCALADO / decision del USUARIO |

## 6. Plantillas por canal y adjudicacion

- **Bundle de FICHEROS**: rutas absolutas + lista de "verifica X en <ruta>" + presupuesto de
  lecturas, y NINGUN framing de lente sin ficheros. Una lente con ficheros que recibe un framing sin
  ficheros se autodeclara sin ficheros (es lo que muestran las rondas fallidas). (a)
- **Bundle de TEXTO**: contrato por contenido + framing sin ficheros + tamano maximo POR MODELO
  (declarado en el perfil). Nunca se le pide a una lente de texto "comprueba si existe X". (a)
- **Integridad**: el bundle lleva la version de la plantilla y el hash de cada fuente incrustada, y
  el validador comprueba que cada seccion termina donde dice, no solo los marcadores. La integridad
  del bundle (version de plantilla, sha256 de cada fuente incrustada y fin de cada seccion) la valida
  el ADAPTADOR o la HERRAMIENTA del sistema antes de lanzar; el nucleo fija el contrato, no el
  validador. (a)
- En el bucle de una propuesta, la lente de FICHEROS recibe tambien el prompt canonico que la
  propuesta modifica. (b)
- **Prompt del ejecutor**: generalizado desde la plantilla canonica; declara objetivo, tipo de
  entrega, criterio de hecho y barreras. (a)
- **Adjudicacion por ronda (M3)**: por ronda se registra `lente_pedida, lente_que_respondio,
  identidad, hallazgo, tipo, verificacion, efecto, correcto, util, adoptado, motivo` (esquema en la
  seccion 7). (a)
- **Metricas por ciclo**: un registro por ciclo (seccion 8). (a)
- **Citas**: por NOMBRE DE SECCION en todo texto durable; la referencia a linea solo en evidencia
  fechada y con el hash del documento citado. (a)

## 7. Esquemas ejecutables

Los cuatro esquemas usan un subconjunto minimo de JSON Schema: `type`, `required`, `properties`,
`enum`, `items`, `minItems`, `minLength`. El perfil se valida antes de lanzar; la adjudicacion y las
rondas se validan al registrar. Una capacidad que el perfil NO declara se rige por su nivel degradado
de la seccion 3.

**SCHEMA: perfil** (que cubre cada capacidad, su nivel degradado, su version y los minimos del tipo)

```json
{
  "type": "object",
  "required": ["version", "minimos_por_tipo", "verificadores_minimos_gobierno", "capacidades"],
  "properties": {
    "version": {"type": "string", "minLength": 1},
    "minimos_por_tipo": {"type": "object"},
    "verificadores_minimos_gobierno": {"type": "integer"},
    "capacidades": {
      "type": "object",
      "required": ["LECTOR_FS", "EJECUTOR", "EVIDENCIA", "REGISTRO_RONDAS", "IDENTIDAD"],
      "properties": {
        "LECTOR_FS": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "LENTE_TEXTO": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "EJECUTOR": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "EVIDENCIA": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "REGISTRO_TRABAJO": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "REGISTRO_RONDAS": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "BARRERAS": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "CANAL_SESIONES": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "DECISIONES": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "IDENTIDAD": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]},
        "ESCALADO": {"type": "object", "required": ["comando", "version", "prueba_de_vida", "nivel_degradado"]}
      }
    }
  }
}
```

`minimos_por_tipo` lleva, por tipo de entrega del sistema, un entero >= 1 de identidades
independientes; `verificadores_minimos_gobierno` es un entero >= 1. Ambos son parametros del
ADAPTADOR, no numeros fijos del nucleo.

**EJEMPLO BUENO: perfil**

```json
{
  "version": "1",
  "minimos_por_tipo": {"code": 3, "documentation": 2},
  "verificadores_minimos_gobierno": 1,
  "capacidades": {
    "LECTOR_FS": {"comando": "cli-lector", "version": "1", "prueba_de_vida": "responde con cita a una ruta dada", "nivel_degradado": "EXPLORATORIO"},
    "EJECUTOR": {"comando": "cli-ejecutor", "version": "1", "prueba_de_vida": "escribe un artefacto con su log", "nivel_degradado": "implementador-manager"},
    "EVIDENCIA": {"comando": "vcs", "version": "1", "prueba_de_vida": "foto antes y despues del arbol", "nivel_degradado": "hash-por-fichero"},
    "REGISTRO_RONDAS": {"comando": "jsonl", "version": "1", "prueba_de_vida": "una fila por ronda registrada", "nivel_degradado": "declarado"},
    "IDENTIDAD": {"comando": "registro", "version": "1", "prueba_de_vida": "clave a proveedor y modelo", "nivel_degradado": "manual"}
  }
}
```

**EJEMPLO MALO: perfil -- sin LECTOR_FS**

```json
{
  "version": "1",
  "minimos_por_tipo": {"code": 3, "documentation": 2},
  "verificadores_minimos_gobierno": 1,
  "capacidades": {
    "EJECUTOR": {"comando": "cli-ejecutor", "version": "1", "prueba_de_vida": "escribe un artefacto con su log", "nivel_degradado": "implementador-manager"},
    "EVIDENCIA": {"comando": "vcs", "version": "1", "prueba_de_vida": "foto antes y despues del arbol", "nivel_degradado": "hash-por-fichero"},
    "REGISTRO_RONDAS": {"comando": "jsonl", "version": "1", "prueba_de_vida": "una fila por ronda registrada", "nivel_degradado": "declarado"},
    "IDENTIDAD": {"comando": "registro", "version": "1", "prueba_de_vida": "clave a proveedor y modelo", "nivel_degradado": "manual"}
  }
}
```

**EJEMPLO MALO: perfil -- sin minimos_por_tipo**

```json
{
  "version": "1",
  "verificadores_minimos_gobierno": 1,
  "capacidades": {
    "LECTOR_FS": {"comando": "cli-lector", "version": "1", "prueba_de_vida": "responde con cita a una ruta dada", "nivel_degradado": "EXPLORATORIO"},
    "EJECUTOR": {"comando": "cli-ejecutor", "version": "1", "prueba_de_vida": "escribe un artefacto con su log", "nivel_degradado": "implementador-manager"},
    "EVIDENCIA": {"comando": "vcs", "version": "1", "prueba_de_vida": "foto antes y despues del arbol", "nivel_degradado": "hash-por-fichero"},
    "REGISTRO_RONDAS": {"comando": "jsonl", "version": "1", "prueba_de_vida": "una fila por ronda registrada", "nivel_degradado": "declarado"},
    "IDENTIDAD": {"comando": "registro", "version": "1", "prueba_de_vida": "clave a proveedor y modelo", "nivel_degradado": "manual"}
  }
}
```

**SCHEMA: adjudicacion** (una fila M3 por ronda; exige el campo de verificacion)

```json
{
  "type": "object",
  "required": ["lente_pedida", "lente_que_respondio", "identidad", "hallazgo", "tipo", "verificacion", "efecto", "correcto", "util", "adoptado", "motivo"],
  "properties": {
    "lente_pedida": {"type": "string", "minLength": 1},
    "lente_que_respondio": {"type": "string", "minLength": 1},
    "identidad": {
      "type": "object",
      "required": ["proveedor", "modelo"],
      "properties": {
        "proveedor": {"type": "string", "minLength": 1},
        "modelo": {"type": "string", "minLength": 1}
      }
    },
    "hallazgo": {"type": "string", "minLength": 1},
    "tipo": {"type": "string", "enum": ["hecho", "preferencia", "diseno"]},
    "verificacion": {"type": "string", "enum": ["comando", "cita", "no_verificable_a_verificador"]},
    "efecto": {"type": "string", "enum": ["cambia-objeto", "cambia-decision", "historico", "descartado"]},
    "correcto": {"type": "boolean"},
    "util": {"type": "boolean"},
    "adoptado": {"type": "boolean"},
    "motivo": {"type": "string"}
  }
}
```

**EJEMPLO BUENO: adjudicacion**

```json
{
  "lente_pedida": "lente-a",
  "lente_que_respondio": "lente-a",
  "identidad": {"proveedor": "proveedor-a", "modelo": "modelo-a"},
  "hallazgo": "falta la barrera de anclaje de la ronda",
  "tipo": "hecho",
  "verificacion": "cita",
  "efecto": "cambia-objeto",
  "correcto": true,
  "util": true,
  "adoptado": true,
  "motivo": "el hallazgo se reprodujo con la cita"
}
```

**EJEMPLO MALO: adjudicacion -- sin campo de verificacion**

```json
{
  "lente_pedida": "lente-a",
  "lente_que_respondio": "lente-a",
  "identidad": {"proveedor": "proveedor-a", "modelo": "modelo-a"},
  "hallazgo": "falta la barrera de anclaje de la ronda",
  "tipo": "hecho",
  "efecto": "cambia-objeto",
  "correcto": true,
  "util": true,
  "adoptado": true,
  "motivo": "el hallazgo se reprodujo con la cita"
}
```

**SCHEMA: ronda_ficheros** (la ronda de una lente CON ficheros; exige recibo y citas `ruta:linea`)

```json
{
  "type": "object",
  "required": ["canal", "lente", "recibo_de_lectura", "salida", "citas"],
  "properties": {
    "canal": {"type": "string", "enum": ["FICHEROS"]},
    "lente": {"type": "string", "minLength": 1},
    "recibo_de_lectura": {
      "type": "object",
      "required": ["llamadas", "leyo"],
      "properties": {
        "llamadas": {"type": "integer"},
        "leyo": {"type": "boolean"}
      }
    },
    "salida": {"type": "string", "minLength": 1},
    "citas": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}
  }
}
```

**SCHEMA: ronda_texto** (la ronda de una lente SIN ficheros; sin recibo; referencias al bundle)

```json
{
  "type": "object",
  "required": ["canal", "lente", "salida", "referencias", "no_verificables"],
  "properties": {
    "canal": {"type": "string", "enum": ["TEXTO"]},
    "lente": {"type": "string", "minLength": 1},
    "salida": {"type": "string", "minLength": 1},
    "referencias": {"type": "array", "items": {"type": "string", "minLength": 1}},
    "no_verificables": {"type": "array", "items": {"type": "string", "minLength": 1}}
  }
}
```

Una lente con FICHEROS cita al menos una referencia `ruta:linea` comprobable; una lente sin ficheros
declara sus `referencias` a los fragmentos del bundle en que apoya su hallazgo (puede ser lista
vacia) y su lista de `no_verificables` sobre los hechos.

**EJEMPLO BUENO: ronda_ficheros**

```json
{
  "canal": "FICHEROS",
  "lente": "lente-a",
  "recibo_de_lectura": {"llamadas": 24, "leyo": true},
  "salida": "hay un hueco en el anclaje de la ronda",
  "citas": ["ruta:linea donde esta el hueco"]
}
```

**EJEMPLO MALO: ronda_ficheros -- lector con ficheros sin citas**

```json
{
  "canal": "FICHEROS",
  "lente": "lente-a",
  "recibo_de_lectura": {"llamadas": 24, "leyo": true},
  "salida": "lo he revisado y esta bien",
  "citas": []
}
```

**EJEMPLO BUENO: ronda_texto**

```json
{
  "canal": "TEXTO",
  "lente": "lente-b",
  "salida": "el contrato del bundle no fija el tamano maximo por modelo",
  "referencias": ["fragmento 3 del bundle: reglas de validez"],
  "no_verificables": ["si la ruta citada existe en el arbol"]
}
```

**EJEMPLO MALO: ronda_texto -- sin campo no_verificables**

```json
{
  "canal": "TEXTO",
  "lente": "lente-b",
  "salida": "el contrato del bundle no fija el tamano maximo por modelo",
  "referencias": ["fragmento 3 del bundle: reglas de validez"]
}
```

## 8. Metricas por ciclo y mejora continua

Por ciclo y por lente se registra: rondas hasta converger; hallazgos, correctos, utiles y adoptados
(M3); lectores que no leyeron; lentes sin ficheros que "confirmaron"; sustituciones; mudos por
modelo y tamano; errores de cifra propios cazados despues; incidentes de agente (mudo, sin
entregable, fallo de transporte); y lecciones aplicadas antes frente a corregidas despues. (a)

**Propiedad de mejora continua medible:** si los planes derivan de una estrategia unica, el ULTIMO
plan debe salir MUCHO mejor que el primero. Criterio operativo del USUARIO: en tres ciclos de una
misma estrategia bajan los incidentes repetidos y suben las lecciones preventivas. Si la serie no
mejora, el ciclo se declara estancado y se escala. Propiedad exigida por diseno, pendiente de medir
en tres ciclos de una misma estrategia. (c)

## 9. Modo implementador=manager

Se mantienen TODAS las fases y bucles; cambia el actor. (a) Cuando no hay EJECUTOR distinto y el propio
MANAGER implementa:

- el bucle sobre el prompt del ejecutor (fase 8) se aplica al plan que el Manager va a ejecutar;
- la revision del ejecutor la sustituye una revision del Manager sobre su PROPIO diff, con al menos
  los verificadores que declare el perfil y lentes de identidad distinta de la del Manager;
- el Manager no adjudica sus propios hallazgos sin comando ("aplicate tu propia vara");
- todos los hallazgos de un bucle van en UN commit con UN bucle anclado y la suite al final.

## 10. Versionado

`contract_id: cid-manager-orchestrator-loop-v1`. El nucleo nunca se ha publicado: la primera
version publicada sera esta v1, y hasta entonces cambiar estados, roles o reglas de validez no exige
nota de migracion; despues de publicarla, si. El perfil declara la version que usa y la proyeccion
la lleva escrita. (b)
