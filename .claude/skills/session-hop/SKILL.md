---
name: session-hop
description: Puente entre sesiones, de solo lectura, que produce el arranque de la sesion siguiente con el METODO heredado y el ESTADO re-medido (cada dato con su comando y exit code) y como mucho lo escribe en orchestrator_pipeline/arranques/. Usar cuando se cierra una sesion para dejar continuidad medida o se prepara el arranque de la siguiente. No usar para definir el rol o el metodo de la sesion siguiente (ver orchestrator_session_bootstrap), para leer el estado de UN ticket (comandos /pause-work, /resume-work y /session-report) ni para ejecutar el trabajo de la sesion.
---

Lee `skills/session-hop/SKILL.md`.
