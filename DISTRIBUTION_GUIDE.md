# Distribution Guide

## Purpose

This template is meant to be copied into a new project and used locally.

## Version contract

- `pyproject.toml` = portable package version
- `.agent/.version_manifest.json` = core/system version
- Both versions must stay documented together

## Canonical commands

```powershell
python scripts/detect_version.py .
python scripts/upgrade.py . --dry-run
python scripts/upgrade.py . --confirm
python scripts/upgrade.py . --verify
python scripts/rollback.py --latest
```

## Legacy aliases

```powershell
python scripts/detect_agent_system_version.py .
python scripts/upgrade_agent_system.py . --dry-run
python scripts/upgrade_agent_system.py . --confirm
python scripts/upgrade_agent_system.py . --verify
```

## Distribution checklist

- Copy the portable folder completely.
- Remove runtime state, caches and logs before shipping.
- Verify the version contract.
- Run the safe test wrapper in the target project.
