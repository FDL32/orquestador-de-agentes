# AGENT_SECURITY.md

## Purpose

Least-privilege policy for the multi-agent template.

Agents may develop, review and validate inside the workspace, but they must not touch secrets, private paths or destructive operations without explicit human approval.

## Hard rules

- Do not store real credentials in the repo.
- Do not edit `privada/`, `.env`, `.ssh`, `.gnupg` or equivalents.
- Do not write outside the project workspace.
- Do not run `git push`, `git reset --hard`, `git clean -fd` or recursive deletes without approval.
- Do not assume an external MCP is safe by default.

## Write control

- `.agent_allowlist.json` = allowed write roots.
- `.agent_denylist.json` = protected paths and command patterns.
- `guard_paths.py` validates those files and blocks dangerous actions.

## Security logging

Blocked actions are logged in `.agent/logs/security.log` with an append-only format.
If logging fails, the block still stands.

## Quality gates

```powershell
python scripts/run_pytest_safe.py
python scripts/run_pytest_safe.py --level all
python .agent/agent_controller.py --validate --json --force
```

## Scope check

`scripts/orquestador.py` can capture before/after snapshots for write-scoped runs.
That is observability only; it does not replace human review or blocking hooks.

## Copy cleanup

Do not copy runtime logs or caches into a new project:

- `.agent/logs/*.log`
- `.agent/test_logs/`
- `.agent/runtime/pytest-safe/`
- `.tmp/`
- `.pytest_cache/`
- `.ruff_cache/`
- `tmp_pytest_*`
