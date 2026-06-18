# Legacy setup checklist

This reference is retained only to identify the pre-host-extends setup flow.
Do not use it as the current installation procedure.

## Superseded instructions

The old checklist asked agents to:

- copy `.agent/` manually into a destination project;
- copy `.agent/rules/` into agent-specific instructions;
- create `privada/` as part of agent-system setup;
- run a local `.agent/agent_controller.py` without an explicit destination root.

Those steps are legacy. The current model uses one external `repo_motor` plus a
linked `repo_destino`.

## Current source of truth

Use `skills/setup-agent-system/SKILL.md` for install/sync.

Expected current flow:

- run `scripts/install_agent_system.py --install --dest <repo_destino> --prefix <XXX>`;
- keep `.agent/config/motor_destination_link.json` in the destination;
- use `active_profile: host-project` for destination installs;
- run operational commands with `--project-root <repo_destino>` or
  `AGENT_PROJECT_ROOT=<repo_destino>`;
- use `prompts/orchestrator_destination_bootstrap.md` only after the destination is installed.

For Git/publication readiness, use:

- `scripts/check_destino_publish_ready.py` for the operational pre-push gate;
- `prompts/audit_git_publication.md` for first-publication exposure review.
