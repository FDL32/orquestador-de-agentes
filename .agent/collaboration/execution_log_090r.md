# Paso 0 Receipt — WOT-2026-090r Guard Baseline

**Fecha:** 2026-10-13 21:45 UTC
**Comando:** `python scripts/check_backlog_contract.py --project-root C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_workspace_wt_kilo_067a`
**Destino:** `C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_workspace_wt_kilo_067a`

## Salida relevante

```
[backlog-contract] lost-id census (WOT-2026-090r): base=backlog=2501 archive=4599 ids=883 | head=backlog=2501 archive=4599 ids=883
```

## Veredicto

**VERDE — No produce falso rojo.** El censo confirma que el estado actual del workspace destino es consistente: 883 IDs en base, 883 IDs en HEAD. Ningún ID perdido detectado.

## Violaciones existentes (no relacionadas a 090r)

- 3 violaciones de dependencia terminal (WOT-2026-074h, WOT-2026-086i, WOT-2026-089p)
- WARNs de ficha con estado live pero ticket terminal en archive (WOT-2026-020l, 020p, 020r, etc.)

Estas violaciones preexistentes no afectan al guard de lost-ids.