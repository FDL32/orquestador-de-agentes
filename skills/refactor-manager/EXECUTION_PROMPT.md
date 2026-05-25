# Refactor Manager - Execution Prompts (cortos)

Prompts cortos para uso diario. Asumen que el agente ya tiene cargado `PROMPT_TEMPLATE.md` y el contrato de `SKILL.md` como contexto base.

## Prompt 1: analisis + plan (sin tocar codigo)

```
Usa las reglas de refactorizacion del repo (skills/refactor-manager/PROMPT_TEMPLATE.md).

Tarea: analiza este proyecto Python para refactorizacion, reingenieria ligera y
optimizacion segura.

No modifiques codigo todavia.

Primero haz:
1. Preflight del repo (Python version, gestor, tooling, git status).
2. Mapa resumido.
3. Deteccion de herramientas y comandos de validacion.
4. Tabla de findings con clasificacion A/B/C/D.
5. Plan por sub-fases (2.1 a 2.4).
6. Recomendacion de la primera sub-fase segura.

Preserva comportamiento, APIs publicas y compatibilidad. No añadas dependencias.
No optimices sin evidencia. Detente antes de aplicar cambios.
```

## Prompt 2: aplicar una sub-fase aprobada

```
Aplica unicamente la sub-fase aprobada: [indicar fase 2.1 / 2.2 / IDs de findings].

Restricciones:
- Cambios pequeños y revisables.
- No cambies comportamiento observable.
- No cambies APIs publicas.
- No añadas dependencias.
- No mezcles refactor con nuevas funcionalidades.
- No mezcles categorias de riesgo en un mismo lote.

Despues de cada lote, muestra:
- Resumen.
- Archivos modificados.
- Diff relevante.
- Comandos de validacion ejecutados (ruff, pytest, mypy segun aplique).
- Resultados.
- Riesgos residuales.

Antes de editar, confirma que archivos tocaras y por que.
```

## Prompt 3: foco en una zona concreta

```
Foco: [paquete / archivo / funcion concreta].

Aplica el flujo de skills/refactor-manager (Fase 1 + Fase 2) restringido a ese
alcance. No salgas del scope. Si encuentras problemas fuera, anotalos como
findings deferidos.
```

## Prompt 4: auditoria "no hace falta refactor"

```
Audita [paquete / archivo] con criterio estricto: si el codigo ya esta bien,
respondelo explicitamente como "no veo oportunidades significativas" y
justifica. Solo lista findings cuando el beneficio supere claramente al
riesgo del cambio.
```

## Prompt 5: tests de caracterizacion antes de refactor

```
El area [X] tiene poca cobertura. Antes de cualquier refactor, propon tests
de caracterizacion que fijen el comportamiento actual observable:
- Inputs reales o representativos.
- Outputs / efectos esperados.
- Edge cases conocidos.

No modifiques la implementacion. Solo entrega los tests propuestos y donde
ubicarlos.
```

---

## Cuando usar cada uno

- **Sesion nueva sobre un repo** → Prompt 1.
- **Plan ya aprobado, hay que ejecutar** → Prompt 2.
- **Solo un modulo conocido como problematico** → Prompt 3.
- **Sospecha de over-refactor o quiero segunda opinion** → Prompt 4.
- **Codigo legacy sin tests** → Prompt 5 antes de Prompt 1.

## Integracion con tickets

Dentro de `orquestador_de_agentes`, cada Prompt 2 corresponde tipicamente a un
ticket WP independiente con su `work_plan.md` y su ciclo Manager -> Builder
completo. No metas multiples sub-fases en el mismo ticket.
