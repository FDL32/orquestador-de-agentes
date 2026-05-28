# Plan Quality Checklist

Usa esta checklist antes de aprobar cualquier `work_plan.md`. Las preguntas son deliberadamente concretas: si una respuesta no puede justificarse con una linea, una seccion o un comando, el plan sigue verde a medias y debe revisarse.

## Objetivo y contexto

- [ ] El objetivo empieza con un verbo directo y nombra el resultado observable.
- [ ] El contexto explica por que el ticket existe y que dolor resuelve.
- [ ] No hay frases vacias como "mejorar", "optimizar" o "hacerlo mejor" sin una consecuencia concreta.

## Alcance

- [ ] La seccion `Non-goals` existe y no esta vacia.
- [ ] `Files Likely Touched` enumera todos los archivos que el plan espera tocar.
- [ ] No hay comodines difusos como "etc.", "los necesarios" o "otros archivos".
- [ ] Si el ticket crea docs o scaffolding, `deliverable_type` no esta clasificado como `code` por inercia.

## Secuencia

- [ ] Las fases siguen un orden que puede ejecutarse sin contradicciones.
- [ ] Ninguna fase exige simultaneamente una accion y su inversa sobre el mismo recurso.
- [ ] Si una fase depende de otra, la dependencia esta nombrada de forma explicita.

## Verificabilidad

- [ ] Cada criterio de aceptacion tiene un verificador literal: test, comando o asercion de archivo.
- [ ] No hay criterios del tipo "observable", "correcto" o "estable" sin una forma concreta de comprobarlos.
- [ ] Si una fase crea un script invocable, el plan declara flags, exit codes esperados y el comportamiento de `--help` antes de entregarlo.
- [ ] Si una fase define una secuencia de checks, cada check se clasifica de forma explicita como `bloqueante` o `informativo`.
- [ ] El `AUDIT_WP` replica exactamente los criterios relevantes del `PLAN_WP`.
- [ ] El `PLAN_WP` no contiene secciones de verificacion como `## TP Check`, `## Evidencia` o `## Blockers`; esas secciones viven en el `AUDIT_WP`.
- [ ] El `TP Check` del `AUDIT_WP` usa `TP-01:`..`TP-05:` en formato canonico y no sustituye la verificacion del plan por criterios de diseno del entregable.

## TP Check

- [ ] TP-01 Contradiccion secuencial: el plan no pide acciones incompatibles sobre el mismo recurso.
- [ ] TP-02 Criterio no verificable: cada aceptacion tiene un verificador literal.
- [ ] TP-03 Deriva de ambito implicita: los archivos tocados estan enumerados sin comodines.
- [ ] TP-04 Semantica blanda: no hay "si procede" ni "stale" sin definicion operativa.
- [ ] TP-05 Paridad PLAN/AUDIT rota: el plan y el audit describen la misma secuencia y los mismos observables.
- [ ] TP-05 Paridad PLAN/AUDIT rota: los verbos y condiciones de `Blockers` y `Fases` permanecen alineados.
- [ ] TP-07 Alcance condicional: el plan no delega a "si existe", "si se anade" o "si aplica" una decision de alcance que deberia estar cerrada.

## Redaccion para prompts

- [ ] Las instrucciones importantes estan al final del bloque de contexto, no escondidas entre ejemplos.
- [ ] Si hay ejemplos, son pocos, relevantes y contrastan `NO` / `SI`.
- [ ] El texto puede pegarse en un prompt sin perder el orden de lectura.

## Salida

- [ ] Si cualquier casilla clave falla, el plan no se aprueba y se corrige antes del handoff.
- [ ] Si todas las casillas clave pasan, el plan puede pasar a `APPROVED`.
- [ ] Si el ticket introduce una nueva gate de calidad, el Manager la aplica manualmente sobre su propio `AUDIT_WP` antes de confiar en automatizacion futura.
