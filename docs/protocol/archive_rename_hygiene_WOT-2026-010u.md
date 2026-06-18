# Archive rename hygiene — barrera de rename de archivado (WOT-2026-010u)

> Convierte un patron recurrente (archivado en limbo que bloquea el siguiente
> ticket) en una barrera temprana, accionable y fail-closed. NO hace auto-commit.

## El problema

`scripts/archive_collaboration_artifacts.py` mueve los `STRATEGY_/AUDIT_/PLAN_`
de un ticket cerrado a `.agent/collaboration/_archive/plan_audit/` con
`shutil.move` — **sin** `git add` ni commit. Git queda en un estado de
**rename no commiteado**:

```
 D .agent/collaboration/AUDIT_WOT-XXXX.md
?? .agent/collaboration/_archive/plan_audit/AUDIT_WOT-XXXX.md
```

La deteccion ya existia (`contaminacion_productiva` en `agent_controller`,
`pre_handoff_guard`, `delivery_hygiene_check`), pero **llega tarde**: salta en el
`validate`/handoff del SIGUIENTE ticket, no en el cierre que lo causa. En una
sola sesion bloqueo tres tickets seguidos (010l->010i, 010g->010h, 010t->010s),
cada uno con la misma reconciliacion manual.

## La barrera

`scripts/delivery_hygiene_check.py::check_archive_rename_complete(project_root)`:

- parsea `git status --porcelain --untracked-files=all` (el flag es necesario:
  git colapsa un directorio nuevo como `_archive/` a su nivel superior y oculta
  el archivo renombrado);
- empareja un **delete** de `.agent/collaboration/(STRATEGY_|AUDIT_|PLAN_)*` con
  una copia **untracked** del mismo basename bajo `_archive/plan_audit/`;
- si hay par(es), devuelve `passed=False`, razon estable
  `archive_rename_uncommitted`, y un diagnostico self-service que nombra origen,
  destino y el comando exacto de remediacion.
- se ejecuta como Verificacion 5 en `main()`, independiente de `--check-tree`.

### Diagnostico (ejemplo)

```
[FAIL] ARCHIVE_RENAME_UNCOMMITTED
      archive_rename_uncommitted: el archivador movio artefactos cerrados a
      _archive/plan_audit/ pero el rename no quedo commiteado (delete+untracked).
        origen: .agent/collaboration/AUDIT_WOT-XXXX.md
        destino: .agent/collaboration/_archive/plan_audit/AUDIT_WOT-XXXX.md
      Remediacion (registra el rename, no borra): git add -- <old> <new> && git commit ...
```

## Lo que NO hace (decisiones de diseno)

- **No auto-commit.** Un commit-sorpresa dentro del archivador mezclaria estado
  vivo del usuario con el rename. La barrera detecta y remedia; el flujo de
  cierre commitea. (CEM: barrera antes que comodidad.)
- **No borra nada.** La remediacion preferida es `git add` de ambos lados
  (rename 100% trazable), nunca `git rm` del historico.
- **Cero falsos positivos.** Un delete SIN copia archivada es dirty normal y NO
  se reporta aqui (lo cubre `check_git_tree_clean`). Archivos no relacionados se
  ignoran.

## Por que no se cambio el archivador

El contrato eligio la opcion B (guard) sobre la opcion A (archivador
auto-commit). El archivador sigue siendo un mover puro y predecible; la
responsabilidad de commitear queda donde ya vive (cierre/handoff), con la barrera
garantizando que no se olvide. Esto evita acoplar el archivador a git y mantener
su idempotencia.

## Tests (barrera verificada)

- `tests/unit/test_delivery_hygiene_check.py`: repo git real; reproduce el limbo
  (AUDIT/STRATEGY/PLAN), verifica razon estable + remediacion + no-auto-commit +
  no-delete; y los no-falso-positivo (delete sin copia, archivo no relacionado,
  arbol limpio).
- `tests/test_archive_collaboration_artifacts.py`: invoca el archivador REAL,
  confirma que mueve sin commitear y que la barrera cata el limbo; tras stage de
  ambos lados, la barrera vuelve a verde.
