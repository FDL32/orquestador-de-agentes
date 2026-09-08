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

## Cuando ejecutar

Al arrancar sesion (Paso 0-ante) y por GRUPO de trabajo, no solo al inicio.
El hook `SessionStart` ya inyecta el indice al abrir sesion en backends que
lo soportan; si el backend no dispara hooks, ejecutar `--bootstrap` manualmente.
