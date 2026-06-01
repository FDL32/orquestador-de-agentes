# Agent System v5 - Reference

## Comandos principales

### Tests
```
python scripts/run_pytest_safe.py
```

### Validación estructural
```
python .agent/agent_controller.py --validate
```

#### Modelo B (motor separado del workspace):
```
python orquestador_de_agentes/.agent/agent_controller.py --validate --json --force --project-root <workspace>
```

### Estado del sistema
```
python .agent/agent_controller.py
```

## Higiene operativa

-  se rota automáticamente en . No podar manualmente.
-  se archiva solo si el bus prueba cierre (SUPERVISOR_CLOSED o REVIEW_DECISION approve).
- Bootstrap: leer  al inicio de cada sesión.
- Secretos: nunca en el árbol del agente. Usar variables de entorno desde .
