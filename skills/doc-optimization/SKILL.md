---
name: doc-optimization
version: 1.0.0
description: Protocolo medir, mover y verificar para trasladar contenido de un fichero siempre-cargado (CLAUDE.md, AGENTS.md y sus @imports) a una referencia, con guard de no-degradacion de sus consumidores. Usar cuando el cierre transitivo de lo siempre-cargado supera alguno de los gates absolutos por-backend de `prompts/doc_optimization.md` PASO 1 (bytes para Codex, caracteres para Claude Code -- nunca un % de ventana). No usar para anadir contenido nuevo, recortar prompts por longitud, acelerar la suite (ver suite-optimization) ni optimizar la memoria (ver memory_optimization).
triggers: [/doc-optimization, doc-optimization, optimizar-documentacion]
author: agent
role: manager
stage: implement
writes_memory: false
quality_gate: false
tags: [core, system, documentation, context, codeonly]
source_prompt: prompts/doc_optimization.md
contract_id: cid-doc-optimization-v1
---

# doc-optimization

Skill para optimizar la documentacion **siempre-cargada** de una raiz basandose en
evidencia medida, no en la apariencia de longitud. Es el hermano de
`suite-optimization`: aquel optimiza SEGUNDOS de suite, este optimiza TOKENS de
contexto. Mismo metodo, otra superficie.

NO reimplementa el metodo: el flujo completo (declarar raiz, medir el cierre
transitivo, clasificar por via de carga y por funcion, las CINCO condiciones, las
trampas verificadas, el guard de no-degradacion) vive en
`prompts/doc_optimization.md`. **El prompt es la fuente de verdad; si algo
diverge, prevalece el prompt.**

## Cuando usarla

- El cierre transitivo de lo `siempre-cargado` de una raiz supera alguno de los
  gates por-backend de `prompts/doc_optimization.md` PASO 1, y se quiere reducir
  SIN perder contrato normativo.
- Antes de anadir contenido nuevo a un fichero que ya entra en cada sesion.

## Cuando NO usarla

- Para recortar un `router-condicional` por longitud: su tamano ES su funcion.
- Para editar a mano un fichero `generado`: su tope vive en el script generador.
- Para "acortar porque es largo" sin medir contra los gates del prompt. La
  apariencia de longitud no es evidencia.
- Si no puedes EJECUTAR los consumidores del fichero: sin before/after de su
  salida real no se mueve nada.

## El invariante (unico criterio portable)

> El cierre transitivo de `siempre-cargado` cabe DENTRO DE CADA gate por-backend.

Ver `prompts/doc_optimization.md` seccion "El invariante" y PASO 1 para las
cifras vigentes y su fuente (gates absolutos en bytes/caracteres, no un % de
ventana: ningun backend medido calcula un porcentaje de su contexto). Esta
skill no redeclara las cifras -- remite al prompt, que es la fuente de verdad
(X-09: skill apunta, prompt gobierna).

## Las CINCO condiciones (detalle en el prompt)

Un bloque solo se mueve si cumple TODAS:

1. **(a) Concentrado** -- seccion contigua de funcion unica.
2. **(b) Destino alcanzable** -- y el destino debe ser `referencia-bajo-demanda` o
   `router-condicional`; mover a `citado-obligatorio` es cambiar de bolsillo.
3. **(c) No es refutacion** -- ni entera ni repartida entre secciones.
4. **(d) Ningun consumidor programatico consume ESE bloque** -- un parser no sigue
   enlaces.
5. **(e) No esta dentro de una seccion que un consumidor extraiga por ENCABEZADO.**

## Trampas verificadas (no re-descubrir)

Esta skill NO redeclara las cifras de evidencia (X-09: remite, no redeclara -- unas cifras sin
fecha caducan en silencio). Ver `prompts/doc_optimization.md` seccion "TRAMPAS VERIFICADAS"
para el detalle completo con evidencia fechada:

- **TRAMPA-1:** la medicion miente sin raiz declarada (mismo nombre de fichero, raices
  distintas).
- **TRAMPA-2:** contar el fichero suelto miente con `@import` -- el cierre, no el fichero raiz,
  es lo que se mide contra los gates.
- **TRAMPA-3:** "0 lineas perdidas" es un CONTEO, no un guard -- verifica la SALIDA del
  consumidor, no el conteo del fichero.

## Guard obligatorio al aplicar

Before/after del fichero **y de la SALIDA de cada consumidor censado**. Si la
seccion extraida encoge, el traslado esta estripando contexto aunque el origen
conserve un puntero. **Si no puedes ejecutar el consumidor, no puedes mover el
bloque.**

## Estados terminales validos

`APLICADO` / `SIN CANDIDATO MOVIBLE` / `NO APLICA` (ya cumple TODOS los gates aplicables) /
`BLOQUEADO` (consumidor no ejecutable o no se puede medir el gate aplicable).

Concluir "aqui no hay nada que recortar" es un RESULTADO, no una corrida fallida.

## Prompt canonico

Leer y aplicar `prompts/doc_optimization.md`. Hereda filosofia CEM de
`prompts/audit_agent_output.md` y la forma de `prompts/suite_optimization.md`.
Expediente de evidencia: ver "Expediente de evidencia" en el prompt canonico -- no hace falta
leerlo para ejecutar.

## Restriccion dura

- SOLO UN fichero por corrida (no un sweep).
- **SUELO:** alcanzados TODOS los gates aplicables, el protocolo no se aplica mas a ese
  fichero. El objetivo es el invariante, no el minimo.
- Ante duda entre "movible" y "adyacente al error": es adyacente -> NO mover.
- La skill es puntero: no redeclara el metodo. Remite al prompt.
