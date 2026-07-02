# Finding Triage Protocol

contract_id: cid-finding-triage-v0

Usalo cuando durante un ticket, review o cierre de sesion aparezca un hallazgo
nuevo que no estaba claramente dentro del contrato original. Objetivo: decidir
si el agente puede actuar autonomamente, si debe dejar follow-up, o si necesita
GO humano.

Regla base: no todo hallazgo descubierto durante un ticket pertenece a ese
ticket. Clasifica antes de tocar codigo, memoria o backlog.

| Caso | Accion autonoma por defecto |
|------|------------------------------|
| Bloquea el criterio de aceptacion del ticket actual | Resolver en el mismo ticket. Registrar evidencia y mantener el diff dentro del FLT o justificar scope. |
| Es regresion introducida por el diff actual | Resolver en el mismo ticket. Exigir test/regresion o verificacion focal. |
| Es bug preexistente pero impide cerrar gates obligatorios | Hotfix solo si es 1-3 lineas, bajo riesgo, test aislado, sin cambio de contrato/arquitectura, y se registra como `preexisting gate unblock`. Si toca produccion o cambia comportamiento, abrir ticket nuevo. |
| Es deuda/preexistente y no bloquea el deliverable | Registrar backlog/follow-up con evidencia. No tocar en el ticket actual. |
| Requiere cambiar contrato, Files Likely Touched, arquitectura o superficie nueva | Ticket nuevo o Contract Formation. No resolver en caliente. |
| Es incidente urgente de seguridad, PII o exposicion remota viva | Pausar ticket activo y abrir hotfix dedicado con checkpoint humano. Usar `--pause-ticket`/`--resume-ticket` cuando aplique. |
| Es solo documentacion, memoria u observacion | Registrar como sugerencia no bloqueante o memoria, segun `memory_upload.md`. No mezclar con codigo. |

Nota operativa para tickets motor-self: `--pause-ticket`/`--resume-ticket` y demas
write-ops del controller requieren `AGENT_PROJECT_ROOT` apuntando al motor. El guard
`is_motor_code_only` bloquea esas operaciones si no hay workspace externo configurado.

Autonomia permitida:
- Mismo ticket: solo para blockers del contrato actual o regresiones del diff actual.
- Hotfix preexistente: solo si cumple todos los limites de bajo riesgo y desbloquea un gate obligatorio.
- Backlog/follow-up: para deuda real con evidencia que no bloquea el deliverable.

GO humano obligatorio:
- cambios irreversibles o alto blast-radius;
- incidente seguridad/PII/remoto;
- ampliar contrato/FLT/arquitectura;
- hotfix preexistente que toque produccion o comportamiento observable;
- cualquier caso ambiguo donde dos clasificaciones cambien el resultado del ticket.

Evidencia minima por clasificacion:
- claim original o sintoma;
- comando/diff/SHA/ruta que lo verifica;
- decision de triage elegida;
- por que no es scope creep.
