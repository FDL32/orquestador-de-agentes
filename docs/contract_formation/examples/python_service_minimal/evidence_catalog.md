# evidence_catalog.md -- python_service_minimal

| ID | Fuente | Tipo | Fiabilidad | Claim | Corroboracion | Decisiones afectadas | Riesgo injection |
|----|-------|------|-----------|-------|--------------|-----------------------|-----------------|
| EVID-001 | Documentacion oficial FastAPI | official_doc | alta | FastAPI minimo endpoint GET con JSON | Verificado con ejemplo local | DEC-EX-001 | bajo |
| EVID-002 | Conversacion usuario: servicio minimo health check | user_doc | alta | Objetivo es un solo endpoint sin persistencia | Fuente primaria | DEC-EX-002 | nulo |
| EVID-003 | Conocimiento stdlib http.server | inferred | media | stdlib puede servir HTTP sin dependencias | Solo opcion alternativa | DEC-EX-001 alternativa | bajo |

EVID-003 es inferida/media: no puede sostener sola una DEC-T1a sin corroboracion independiente.
