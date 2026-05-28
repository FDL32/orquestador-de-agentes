# Taxonomia de alcance

## Valores de alcance

| Alcance | Significado | Uso por defecto |
|---|---|---|
| `local` | Relevante solo para el repositorio o proyecto actual | Aprendizajes especificos del proyecto |
| `generalizable` | Valioso para el motor o para la mayoria de repos con el mismo flujo | Patrones entre proyectos |
| `dudoso` | Aun no hay suficiente senal; mantener en cola de revision | Requiere revision humana y TTL |

## Guia de clasificacion

Usar la propuesta del agente como punto de partida y dejar que el usuario apruebe o sobreescriba.

### Preferir `generalizable` cuando

- El problema seguiria existiendo en otro proyecto
- La solucion cambia tooling compartido, skills, scripts o prompts
- El aprendizaje describe un flujo o patron, no un hecho especifico del proyecto

### Preferir `local` cuando

- La leccion depende de datos de dominio o nomenclatura del proyecto
- La solucion solo tiene sentido en el repositorio actual
- La observacion esta atada a convenciones o artefactos especificos del proyecto

### Preferir `dudoso` cuando

- El aprendizaje parece util pero la senal es debil
- El mismo problema no se ha repetido todavia
- El agente no puede justificar el alcance con confianza

## Regla de promocion

- Tres aprendizajes similares de proyectos distintos justifican abrir un WP de mejora del motor
- No convertir automaticamente un unico learning en regla compartida
- Mantener al humano en el bucle para la promocion final
