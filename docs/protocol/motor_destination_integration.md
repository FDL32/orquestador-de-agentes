# Gate integrado motor-destino (WOT-2026-008f)

`scripts/check_motor_destination_integration.py` es un gate unico que valida el
engranaje motor-destino y el lifecycle operativo **delegando** en checks vivos,
sin reinventar validadores ni mutar un `repo_destino` real.

## Uso

```powershell
python scripts/check_motor_destination_integration.py --project-root <repo_destino> [--motor-root <repo_motor>]
python scripts/check_motor_destination_integration.py --project-root <repo_destino> --audit-publication
```

- `--project-root` (obligatorio): ruta al `repo_destino` (workspace activo).
- `--motor-root` (opcional): si se omite, se resuelve desde el link.
- `--audit-publication` (opcional): corre la auditoria de primera publicacion
  (dry-run, mas cara). Por defecto solo corre el gate operativo pre-push.

## Exit codes

| Code | Significado |
|------|-------------|
| 0 | Integracion OK (gate operativo verde; auditoria limpia si se pidio). |
| 1 | Un check fallo (autoridad, publish-ready con errores, o hallazgo de auditoria). |
| 2 | Pre-push reporta estado no publicable pero sin errores (gate de STATUS). |
| 3 | Error de configuracion (link ausente/invalido, project root inexistente). |

## Checks (en orden, corta en el primer fallo)

1. **Link** — `motor_destination_link.json` resuelve `motor_root` **y**
   `destination_root` coherentes con `--project-root`. Falla cerrado (exit 3)
   ante link ausente o invalido. `resolve_motor_link()` solo garantiza
   `motor_root`, asi que el wrapper valida `destination_root` por su cuenta.
2. **Autoridad** — `<project_root>/.agent/collaboration` es la autoridad
   canonica del destino, sin split-brain operativo. Snapshots de backup
   (`.agent/backups/`, `_backups/`) NO cuentan como split-brain.
3. **Contexto** — el contexto destino resuelve el link del motor.
4. **Gate operativo pre-push** — delega en
   `check_destino_publish_ready.main(argv)` y propaga su exit code.
5. **Auditoria de primera publicacion** (opt-in) — delega en
   `classify_publication.build_manifest(repo_root, scan_history=True)` (dry-run,
   nunca muta el repo).

## Reutilizacion (no se duplica logica)

| Pieza viva | Como se delega |
|------------|----------------|
| `check_destino_publish_ready.py` | `main(argv)` por import + propagacion de exit code. NO se reescribe `_run_validate`. |
| `classify_publication.py` | `build_manifest(...)` (helper publico, dry-run). |
| `destination_context.py` | `resolve_motor_link(...)`. |
| `validate_authority.py` | helpers `is_canonical_authority`, `find_all_agent_dirs`, `detect_legacy_copies` por import. NO se usa `main()` (es CLI-only y valida el motor). |

### Nota sobre `validate_authority.py`

El contrato preveia extraer un helper exportable en `validate_authority.py`. El
hook de seguridad `guard_paths` protege rutas que casan el patron `auth`, por lo
que editar ese archivo queda bloqueado. La logica de autoridad de destino vive
por tanto en el propio wrapper (`check_destination_authority`), reutilizando los
helpers ya exportables por import. Es mas restrictivo que el plan (cero cambios
en el archivo protegido) y cumple igual "reutiliza via import, no via `main()`".

## Limites

- No es un orquestador generico de session-close.
- No duplica scanners de secretos ni `validate`.
- La auditoria historica solo corre con `--audit-publication` para no mezclar un
  gate pre-push con un scan de historia mas caro.
- Las pruebas usan layouts aislados en `tmp_path`; nunca mutan un destino real.

## Reproduccion de los tests

```powershell
python -m pytest tests/test_check_motor_destination_integration.py -v
```

Cubren: link roto/JSON invalido/destination_root incoherente, autoridad
fail-closed y backups-no-split-brain, propagacion de exit codes del gate
delegado (0/1/2/3), auditoria opt-in (no corre por defecto, corre con flag,
falla cerrado ante hallazgo) y regresion roja->verde del wrapper.
