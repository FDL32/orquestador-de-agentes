# Upgrade Cleanup Guide (Legacy)

This document is retained as a compatibility note for older installations.
The canonical upgrade workflow lives in `UPGRADE_GUIDE.md`; the canonical
distribution boundary lives in `DISTRIBUTION_GUIDE.md`.

## Current Contract

- Keep `UPGRADE_GUIDE.md` at the motor root. Do not archive it into `.session/`.
- Use `scripts/detect_version.py`, `scripts/upgrade.py`, and `scripts/rollback.py`
  as the canonical version/upgrade commands.
- Treat `scripts/cleanup_legacy.py` as a manual maintenance helper, not as part of
  the normal session closeout.
- Never delete `.agent/backups/`, runtime trees, or sandbox test runtime in bulk
  without a human gate and a dry-run.
- Do not write `.session/` cleanup logs in the portable motor model.

## Safe Manual Sequence

```powershell
python scripts/detect_version.py .
python scripts/upgrade.py . --dry-run
python scripts/upgrade.py . --confirm
python scripts/cleanup_legacy.py . --list-only
python scripts/cleanup_legacy.py . --dry-run
```

Only run cleanup with `--confirm` after reviewing the exact files listed by the
dry-run output and confirming that no project state, backups, or test runtime must
be preserved.

## Historical Note

Older revisions of this guide described a copy-ready template model and archived
`UPGRADE_GUIDE.md` under `.session/archive/`. That model is obsolete. The current
architecture keeps the motor portable and code-only, while each `repo_destino`
owns its own `.agent/` collaboration state.
