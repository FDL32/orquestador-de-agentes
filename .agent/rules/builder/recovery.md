# Protocolo de Recuperacion para Builder

Este documento describe el protocolo de recuperacion cuando Builder se pierde, el arbol queda en estado inconsistente, o se necesita volver a un ancla conocido estable.

## Cuando aplicar este protocolo

- Builder perdio el contexto del ticket y no sabe en que estado esta el arbol.
- El arbol tiene cambios no commiteados que no pertenecen al scope del ticket.
- Se necesita volver a un checkpoint conocido (M0-M4) para reanudar desde un punto estable.
- WP-2026-165: Builder borro trabajo ajeno con `git checkout` por interpretar archivos no commiteados como scope externo.

## Pasos de recuperacion

### Paso 1: Parar y evaluar

```bash
# Ejecutar agent_controller para ver estado actual
python .agent/agent_controller.py --json
```

### Paso 2: Verificar estado del arbol con git status

```bash
# Ver archivos modificados, staged, untracked
git status --porcelain

# Ver historial reciente de cambios
git reflog -10
```

### Paso 3: Identificar ultimo ancla estable

Buscar checkpoints semanticos disponibles:

```bash
# Listar todos los checkpoints del ticket
git tag -l "checkpoint/*WP-2026-XXX*"

# Ver detalles de un checkpoint especifico
git show checkpoint/review-WP-2026-XXX
```

Checkpoints disponibles:
- `checkpoint/base-<ticket>` - Inicio del ticket (M0)
- `checkpoint/design-<ticket>` - Diseño aprobado (M1)
- `checkpoint/implementation-<ticket>` - Implementacion completa (M2)
- `checkpoint/review-<ticket>` - Listo para review (M3)
- `checkpoint/closed-<ticket>` - Ticket cerrado (M4)

### Paso 4: Volver al ultimo ancla conocido bueno

**Opcion A: Usar git checkout (Git versions que lo soportan)**

```bash
# Volver al checkpoint de review (M3)
git checkout checkpoint/review-WP-2026-XXX

# O volver a un commit especifico por SHA
git checkout <sha>
```

**Opcion B: Usar git switch --detach (alternativa si checkout no esta disponible)**

```bash
# Modo detach en el checkpoint
git switch --detach checkpoint/review-WP-2026-XXX

# O por SHA
git switch --detach <sha>
```

### Paso 5: Verificar estado despues del checkout

```bash
# Confirmar que el arbol esta limpio
git status --porcelain

# Verificar que estamos en el checkpoint esperado
git describe --tags
```

### Paso 6: Reanudar desde el checkpoint

```bash
# Si necesitas crear una nueva rama desde el checkpoint
git switch -c recovery/WP-2026-XXX

# Reabrir el agente Builder
python .agent/agent_controller.py
```

## Reglas de seguridad

### NO hacer limpieza destructiva

**NO:**
```bash
# NUNCA usar git checkout para borrar archivos fuera de scope
git checkout -- skills/_shared/ticket-anti-patterns.md  # ❌ DESTRUCTIVO
git reset --hard HEAD  # ❌ DESTRUCTIVO
git revert <commit>  # ❌ DESTRUCTIVO sin evaluacion
```

**SI:**
```bash
# Reportar discrepancia en execution_log.md
# Pedir actualizacion explicita del scope al Manager
# Usar checkpoints para volver a anclas conocidas
git checkout checkpoint/review-WP-2026-XXX  # ✅ SEGURO
```

### NO auto-crear checkpoints desde --mark-ready

El checkpoint M3 debe existir **antes** de ejecutar `--mark-ready`. El guard de handoff bloquea si M3 falta.

```bash
# Correcto: crear M3 antes del handoff
python scripts/create_checkpoint.py --milestone M3 --ticket-id WP-2026-XXX
python .agent/agent_controller.py --mark-ready --json --force
```

## Anti-patron AP-D03: Handoff sin ancla de recuperacion

**Descripcion:** Builder intenta hacer handoff sin checkpoint M3 o sin protocolo de recuperacion documental.

**Por que rompe al Builder:** Si el arbol queda en estado inconsistente, no hay forma segura de volver a un punto conocido sin riesgo de perder trabajo.

**Senal de deteccion:**
- `--mark-ready` falla por falta de M3
- `git status` muestra archivos fuera de scope sin ancla de recuperacion
- Builder usa `git checkout` destructivo en lugar de checkpoints

**Prevencion:**
1. Crear M3 explicitamente antes de `--mark-ready`
2. Seguir este protocolo de recuperacion si el arbol se ensucia
3. Nunca usar limpieza destructiva sobre archivos fuera de scope

## Referencias

- `scripts/create_checkpoint.py` - Creacion de checkpoints semanticos M0-M4
- `scripts/pre_handoff_guard.py` - Guard que verifica M3 y arbol limpio antes de handoff
- `.agent/agent_controller.py` - Invoca el guard en `_handle_mark_ready()`
- `skills/_shared/ticket-anti-patterns.md` - AP-D03: Handoff sin ancla
