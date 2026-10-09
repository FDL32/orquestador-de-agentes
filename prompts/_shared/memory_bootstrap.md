# Mecanismo de carga de memoria (WOT-2026-058c)

<!-- contract_id: T-058C-001 / WOT-2026-058c -->

## Por que este doc existe

Las superficies gobernantes (prompts, skills, rules) no cargan memoria por si
mismas. Este fichero es la UNICA fuente del mecanismo de carga, centralizado
una sola vez para evitar que el contrato se replique N veces (la divergencia
ya costo en el pasado: obs-stable-finding-volatile-method).

## Comandos canonicos

```bash
# Cargar indice de memoria (paso 0-ante de cualquier sesion):
python <MOTOR_ROOT>/scripts/memory_context.py --bootstrap

# Expansion dirigida -- obligatoria antes de medir o disenar:
python <MOTOR_ROOT>/scripts/memory_context.py --recall --query "<termino>" --limit 10
python <MOTOR_ROOT>/scripts/memory_context.py --recall --id obs-<slug>
```

`--recall --id` es fail-closed: si el slug no existe, devuelve error.

## Regla del indice

El indice que devuelve `--bootstrap` contiene lineas marcadas `...[truncated]`
que son TITULARES con su `id`. La leccion completa vive despues del corte;
se expande con `--recall --id obs-<slug>`.

## Profundizacion vertical por FAMILIA (domain, WOT-2026-096a)

El `memory_profile.md` (L3) que `--bootstrap` incluye trae, ademas del
contador por domain, una seccion `## Family Summaries` con un resumen corto
(top-2 por `confidence`/recencia) de CADA domain con >=1 observacion -- el
eje de "de que TEMA quiero profundizar" (ortogonal al eje de profundidad
L0/L1/L2). Esa seccion es un INDICE, no el desglose completo.

Para profundizar verticalmente en un domain concreto, la ruta NO es
`--recall --query <termino libre>` (busqueda por similitud, sin garantia de
devolver TODAS las reglas de ese domain): es el desglose dedicado, sin
capar por cardinalidad, `bus/memory_loader.py::get_review_context(domain=
"<domain>")`. **Hoy esta funcion NO tiene flag de CLI propio** -- solo se
invoca desde Python (hoy, el unico consumidor en produccion es el review
bridge del Manager, `bus/review_observations.py`). Un agente que quiera
este desglose completo desde una sesion normal lo hace con un snippet corto
(`python -c "from bus.memory_loader import get_review_context;
print(get_review_context(domain='<domain>'))"` con `sys.path` apuntando al
`<MOTOR_ROOT>`), no con un flag que no existe -- exponer un `--domain` en
`memory_context.py` es trabajo NO incluido en este ticket (WOT-2026-096a),
que solo pide que el bootstrap DECLARE la ruta, no que la convierta en CLI.
La cadena completa de profundizacion es: resumen de `Family Summaries`
(L3') -> desglose completo del domain (L2', `get_review_context`) ->
observacion cruda individual (L1, `--recall --id obs-<slug>`).

## Cuando ejecutar

Al arrancar sesion (Paso 0-ante) y por GRUPO de trabajo, no solo al inicio.
El hook `SessionStart` ya inyecta el indice al abrir sesion en backends que
lo soportan; si el backend no dispara hooks, ejecutar `--bootstrap` manualmente.
