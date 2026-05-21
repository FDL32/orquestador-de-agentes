# Upgrade Guide

This guide documents the version contract and the upgrade command families.

## Version contract

- `pyproject.toml` defines the portable package version.
- `.agent/.version_manifest.json` defines the installed core version.
- The two must be kept in sync in the docs, but they are not the same value.

## Canonical commands

- `python scripts/detect_version.py .`
- `python scripts/upgrade.py . --dry-run`
- `python scripts/upgrade.py . --confirm`
- `python scripts/upgrade.py . --verify`
- `python scripts/rollback.py --latest`

## Legacy aliases

- `python scripts/detect_agent_system_version.py .`
- `python scripts/upgrade_agent_system.py . --dry-run`
- `python scripts/upgrade_agent_system.py . --confirm`
- `python scripts/upgrade_agent_system.py . --verify`

## Recommended workflow

1. Run the canonical detector first.
2. Use `--dry-run` before any upgrade.
3. Apply the upgrade only after reviewing the diff.
4. Verify the result.
5. Roll back only if verification fails.

## Portable notes

- Keep `README.md`, `PROJECT.md` and `AGENTS.md` aligned.
- Preserve the canonical/legacy distinction when you copy the template.
