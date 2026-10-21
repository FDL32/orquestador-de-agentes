# Contrato de Implementacion — <TICKET>

> Este contrato se lee ANTES de que el Builder ejecute cualquier cambio.
> Solo se genera despues de aprobacion humana + admit de follow-ups
> + plan review APPROVE (seccion 5.2 del prompt `repo_audit_multiagent.md`).

**Fecha:** <YYYY-MM-DD>
**Ticket / Informe:** <ID o enlace al informe de auditoria>
**Commit base:** <sha> (ante-posterior al momento de generar este contrato)

---

## 1. Base

- **Hallazgos confirmados** (Fase 4 `veredicto_adversarial == confirmado`):
  - [N-01] — <titulo corto>
  - [N-02] — <titulo corto>
  - ...

- **Seguimiento de plan review** (seccion 5.2):
  - Plan version: <v1 / v2 / ...>
  - Veredicto Revisor: `APPROVE` / `CHANGES` / `REJECT`
  - Si `CHANGES` o `REJECT`: <resumen de los cambios solicitados>

---

## 2. Alcance

### 2.1 Follow-ups a ejecutar

| ID | Descripcion | Files Likely Touched | deliverable_type |
|----|-------------|---------------------|------------------|
| FU-01 | <descripcion breve> | `<archivo>` | <code | doc | test> |
| FU-02 | <descripcion breve> | `<archivo>` | <code | doc | test> |
| ... | ... | ... | ... |

### 2.2 No-goals (explicitamente fuera de alcance)

- <lo que NO se va a tocar, ej. "no modificar la API de exportacion">
- <lo que NO se va a cambiar, ej. "no alterar la estructura del esquema de la base">

---

## 3. Criterios de cierre (binario — PASS/FAIL)

Cada criterio debe poder evaluarse sin interpretacion subjetiva:

- [ ] `pytest`: <X> passed, <Y> failed (cuento exacto)
- [ ] `ruff check`: salida vacia (sin warnings ni errors)
- [ ] `ruff format`: `Would reformat: 0`
- [ ] `gitleaks`: 0 leaks (solo si el contrato toca codigo con secretos)
- [ ] `mutate --check` / `mutation_cycle.py`: <X> survived (solo si hay borrado de codigo sin tests)
- [ ] diff post-implementacion: <X> archivos modificados, <Y> agregados, <Z> eliminados
- [ ] No-goals verificados: <listar los no-goals y confirmar que no se tocaron>

---

## 4. Evidencia requerida

Cada follow-up FU-XX debe dejar al menos una de las siguientes evidencias:

- **Codigo modificado:** diff en `git diff` con el cambio esperado.
- **Test agregado/Modificado:** el archivo de test aparece en `git status` y `pytest` lo pasa.
- **Documento modificado:** diff de .md/.rst con los cambios esperados.
- **Borrado ejecutado:** `git diff --cached -- <archivo>` muestra la eliminacion completa.

---

## 5. Rollback

Si algun criterio de cierre (seccion 3) falla:

1. **Rollback automatico:** `git revert <commit_de_fase6>` (nunca `reset --hard`).
2. **Reporte:** el fallido se marca como `diferido — rollback` en el scorecard.
3. **Reintento:** max 2 intentos antes de escalar al humano.
