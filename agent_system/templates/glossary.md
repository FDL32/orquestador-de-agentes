# Glosario del Sistema Multi-Agente

- **Builder**: Agente encargado de ejecutar cambios técnicos, escribir código y cumplir los TP Checks.
- **EventBus**: Bus de eventos inmutable (`events.jsonl`) que registra cambios de estado y sincroniza agentes.
- **guard_paths**: Sistema de seguridad que impide escrituras accidentales en archivos de estado y código privado.
- **HumanGate**: Umbral de escalado; cuando un ticket falla múltiples revisiones, requiere intervención humana.
- **L1/L2/L3 Memory**: Niveles de retención: L1 (turnos), L2 (reglas de dominio reusables), L3 (políticas globales).
- **Manager**: Agente supervisor que revisa el trabajo del Builder y aprueba/rechaza según métricas de calidad.
- **Microagent**: Documento de conocimiento (ej. onboarding) asociado a keywords para inyectar contexto temprano.
- **ReviewDecision**: Objeto emitido por el Manager (approve, changes, etc.) que determina la transición del ticket.
- **skill_resolver**: Componente que filtra el catálogo de herramientas según los permisos del rol activo.
- **Supervisor**: Motor que orquesta el ciclo de vida de los tickets, coordina agentes y gestiona el EventBus.
- **Ticket (WT-*)**: Unidad atómica de trabajo. Representa un estado en el bus y un contrato de entrega.
- **TP Check**: Trust Policy Check; validaciones estructuradas al final del `work_plan.md` para garantizar resiliencia.
- **TURN.md**: Archivo efímero generado por el controller que indica el rol y plan activo en el turno actual.
- **work_plan.md**: Documento de colaboración canónico donde se detalla el diseño, fases y TP Checks del ticket activo.
