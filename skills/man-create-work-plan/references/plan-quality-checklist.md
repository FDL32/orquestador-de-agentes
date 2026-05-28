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
- [ ] El `AUDIT_WP` replica exactamente los criterios relevantes del `PLAN_WP`.

## TP Check

- [ ] TP-01 Contradiccion secuencial: el plan no pide acciones incompatibles sobre el mismo recurso.
- [ ] TP-02 Criterio no verificable: cada aceptacion tiene un verificador literal.
- [ ] TP-03 Deriva de ambito implicita: los archivos tocados estan enumerados sin comodines.
- [ ] TP-04 Semantica blanda: no hay "si procede" ni "stale" sin definicion operativa.
- [ ] TP-05 Paridad PLAN/AUDIT rota: el plan y el audit describen la misma secuencia y los mismos observables.

## Redaccion para prompts

- [ ] Las instrucciones importantes estan al final del bloque de contexto, no escondidas entre ejemplos.
- [ ] Si hay ejemplos, son pocos, relevantes y contrastan `NO` / `SI`.
- [ ] El texto puede pegarse en un prompt sin perder el orden de lectura.

## Salida

- [ ] Si cualquier casilla clave falla, el plan no se aprueba y se corrige antes del handoff.
- [ ] Si todas las casillas clave pasan, el plan puede pasar a `APPROVED`.
