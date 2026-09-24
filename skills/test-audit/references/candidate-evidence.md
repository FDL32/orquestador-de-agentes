# Candidate Evidence — plantilla obligatoria por candidato

Adaptado de `openclaw/openclaw`. Un candidato sin TODOS estos campos rellenos
NO esta listo para editar. Ausencia de un campo = degradar a "necesita mas
investigacion", nunca proceder a eliminar con el hueco sin llenar.

## Plantilla

```markdown
### CANDIDATO: <nombre exacto del test> (`path/to/test_file.py::TestClass::test_name`)

**Junk pattern citado:** [numero + nombre exacto de `junk-patterns.md`, o "ninguno — retenido por value-bar"]

**Que falla puede detectar realmente hoy:**
[Describe la mutacion/regresion CONCRETA que este test detectaria. Si la
respuesta es "ninguna" o "no estoy seguro", el candidato no esta listo.]

**Callers no-test del seam de produccion cubierto:**
[Lista de callers reales en produccion (scripts/, bus/, hooks/) que ejercen el
mismo camino. Si la respuesta es "ninguno", es señal de seam test-only
(junk pattern 8).]

**Owner-boundary sustituto (mas fuerte, si existe):**
[Nombre + ruta del test que YA cubre el mismo contrato en una frontera igual o
mejor. Si no existe, escribir "no existe — este seria el unico test de este
contrato" y eso EMPUJA hacia retencion, no hacia eliminacion.]

**Historial relevante:**
[`git log -p` resumido: por que se anadio, si es regresion de un bug conocido
(citar ticket si existe), cuanto tiempo lleva sin tocarse.]

**Produccion/test-support que se desbloquea si se elimina:**
[Lista de exports/wrappers/globals que quedarian sin caller si este test se
borra. Si hay alguno, se elimina EN EL MISMO batch (ver `edit-shape.md`), no
se deja como alias.]

**Riesgo y comando de validacion focal:**
[Comando exacto para re-ejecutar el owner-boundary sustituto (o el fichero
completo) tras la eliminacion. Ejemplo:
`python scripts/run_pytest_safe.py --level unit -- tests/unit/test_x.py -k "owner_test"`]

**Casos/aserciones distintos que el candidato ejercita (no solo UNA mutacion):**
[Lista cada caso limite o aserción DISTINTA que el candidato cubre. Una sola
mutacion "representativa" NO basta para declarar el sustituto equivalente —
dos tests pueden detectar la misma mutacion de "borrar la validacion entera"
pero solo uno detectar un caso limite (off-by-one, string vacio, unicode).
Repite el mutation-verify de abajo POR CADA caso distinto que el candidato
ejercita y el sustituto propuesto TAMBIEN debe cubrir; si el sustituto no
cubre alguno, el candidato NO es redundante para ese caso — se retiene o el
sustituto se amplia primero.]

**Mutation-verify (Paso 6, OBLIGATORIO antes de decision final, UNA fila por caso listado arriba):**
- Mutacion concreta a aplicar (describela, ej. "invertir la condicion en
  `line X` de `path.py`"): [descripcion]
- Comando ejecutado — **la mutacion va DENTRO del comando** (tras el segundo
  `--`), NUNCA aplicada a mano antes de invocar el CLI: mutar antes invalida
  el snapshot (`mutation_cycle.py` fotografia DESPUES de arrancar, restauraria
  el mutante). Usa `--level all`, NUNCA `--level unit` (este ultimo
  deselecciona en silencio nodeids marcados `integration`/`eval`/`slow`):
  `python scripts/mutation_cycle.py -- <rutas a proteger> -- python -c "<aplica mutacion + corre run_pytest_safe.py --level all -- <nodeids> + propaga rc>"`
- Resultado CON el candidato presente, owner mutado: [fail esperado / pass inesperado]
- Resultado SIN el candidato (solo el sustituto), owner mutado: [fail esperado / pass inesperado]
- Verificado que el fichero de produccion quedo restaurado tras el ciclo
  (`git diff --stat <ruta>` vacio): [si / no — si "no", el candidato NO esta
  listo, hay un mutante vivo en el arbol]
- Veredicto por caso: [ELIMINAR (para este caso) — el sustituto lo detecta igual | RETENER — el candidato es el unico detector de este caso | NINGUNO DETECTA — ni el candidato ni el sustituto fallan con esta mutacion]

**Veredicto final del candidato (agregado de todos los casos):**
- [ELIMINAR — TODOS los casos tienen veredicto ELIMINAR (sustituto cubre todo)]
- [RETENER — al menos un caso tiene veredicto RETENER (candidato es detector unico de algo)]
- [TEST INUTIL, NO SOLO REDUNDANTE — al menos un caso tiene veredicto NINGUNO
  DETECTA: ni el candidato ni el sustituto detectan esa mutacion. Esto NO es
  "eliminar por redundancia" (el sustituto no cubre nada ahi tampoco) — es
  evidencia de que ESE caso concreto no tiene cobertura real de nadie. Accion:
  (a) si el caso importa, abre un hallazgo de cobertura FALTANTE (Contract
  Formation / ticket nuevo, no parte de este batch de limpieza) antes de
  tocar el candidato; (b) el candidato en si sigue sin proteger ese caso, asi
  que para las mutaciones donde SI aporta valor unico se retiene, y para las
  que no aporta valor en NINGUN lado (ni el ni nadie) se elimina esa aserción
  puntual sin fingir que el sustituto la reemplaza.]
- Nunca declares "ELIMINAR" si algun caso salio "NINGUNO DETECTA" y el caso es
  real (no un artefacto del fixture) — eliminar ahi no es limpieza, es perder
  cobertura sin reemplazo.

**Decision:** [ELIMINAR / CONSOLIDAR con <test> / RETENER / NECESITA MAS INVESTIGACION]
**Razon:** [una frase, con la cita del campo que decidio]
```

## Regla de "campo faltante"

Si CUALQUIER campo de la plantilla queda vacio o con `[NO VERIFICADO]`, el
candidato se reporta como `NECESITA MAS INVESTIGACION`, nunca como `ELIMINAR`.
Esto es identico al invariante anti-fabricacion de `repo-compare`
(`references/output-format.md`): un campo sin evidencia no se rellena con una
suposicion razonable, se marca explicitamente como faltante.

## Persistencia

Cada bloque de candidato va en el reporte persistido de
`.agent/runtime/audit/test_audit/<lane-o-scope>-<YYYY-MM-DD>.md` (gitignored).
No se commitea el reporte; solo el batch de edicion final (tests +
produccion), si se aprueba, se commitea.
