# Credits

External ideas and patterns adopted in this project.

<!-- Convention: one row per WP that adopts an idea from an external repo.    -->
<!-- repo-compare auto-generates a candidate row at the end of each report.   -->
<!-- project-finalize verifies the row exists before closing a WP with        -->
<!-- "Origen externo:" or "Inspired by:" in its work_plan.md.                 -->
<!-- License column is human-verified, never auto-filled.                     -->

| WP | Source | Pattern | License | Adapted vs Ported |
|----|--------|---------|---------|-------------------|
| WP-2026-141 | [google/eng-practices](https://github.com/google/eng-practices) | Code review standards: approval principle, `Nit` convention, and small-CL vocabulary | CC-BY 3.0 | Adapted (text policy only; no code copied) |
| WP-2026-094 | [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) | Post-install host setup hook pattern (`.openhands/setup.sh`) | MIT | Adapted (concept only — our impl detects `.agent/host-setup.{sh,ps1}` from destination, interactive confirmation by default, no code copied) |
| WP-2026-085 | [code-yeongyu/oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) | Config migration framework (_migrations tracking + timestamped backups) | Sustainable Use License v1.0 (source-available, non-commercial) | Adapted (pattern description only, no code copied) |
| WP-2026-082 | [Aider-AI/aider](https://github.com/Aider-AI/aider) | repo-map concept | Apache-2.0 | Inspiration (graphify predates) |
| WP-2026-083 | [garrytan/gbrain@1dadd9e](https://github.com/garrytan/gbrain) | Dream Cycle (memory consolidate) | MIT | Adapted (no LLM, no cron) |
| docs-hotfix-2026-05-18-dify | [langgenius/dify@06f076e](https://github.com/langgenius/dify/tree/06f076e0ff47f2e7c69ebc51e756556dd1030d95) | Docstring-as-spec & Test Rubric (AGENTS.md sections) | Apache-2.0 (modified — Dify Open Source License: no multi-tenant SaaS resale, no LOGO removal in `web/`. Neither restriction applies to text-policy adaptation) | Adapted (re-written policy to match z_scripts Python-only context) |
| WP-2026-096 | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) | Caveman-style doc compression pattern (caveman-compress) | MIT | Inspiration (no code copied, stdlib adaptation only) |
| WP-2026-086 | [NousResearch/hermes-agent@4414a99](https://github.com/NousResearch/hermes-agent/tree/4414a99) | Regex-based redaction module (redact.py secrets & PII scrubbing) | MIT | Adapted (custom regex patterns, recursive payload crawler) |
| hotfix-2026-05-18-skill-collisions | [wshobson/agents@08ded5e](https://github.com/wshobson/agents/tree/08ded5e7b0fe57e7f40194775885eba539c3d8e7) | Agent/skill frontmatter collision detector (name + triggers uniqueness across plugins) | MIT | Ported (glob adapted to skills/*/SKILL.md; extended to also flag duplicate `triggers:` entries — original only checked `name:`) |
| hotfix-2026-05-18-precommit | [deepset-ai/haystack@4c89081](https://github.com/deepset-ai/haystack/tree/4c890818ca293aed8cdeed2791d03c8957556c65) | Defensive pre-commit hook stack (check-ast, end-of-file-fixer, mixed-line-ending --fix=lf, trailing-whitespace) | Apache-2.0 | Adapted (selected 4 hooks from haystack's stack; LF normalization scoped to exclude PowerShell/cmd/bat scripts; runtime artifacts under `.agent/runtime/` excluded) |
| WP-2026-110 | [obra/superpowers](https://github.com/obra/superpowers) | Formal skills for TDD and Debugging | MIT | Adapted (no code copied, process rules adapted to native z_scripts stack) |

---

## Convention

- **Add a row only when an idea originates from an external repo** (not for our own patterns).
- **Source link should pin the SHA** when possible (commit-anchored, not branch-anchored).
- **License column is human-verified**: agent fills `[verify]` if unsure; humans confirm before merge.
- **Adapted vs Ported**:
  - `Ported`: code/text copied with minimal modification.
  - `Adapted`: pattern reused, our implementation differs materially.
  - `Inspiration`: idea sparked, but our implementation predates or differs entirely.

## Propagation note

This file lives at repo root and is **not propagated automatically** to projects derived via `scripts/install_agent_system.py` (which only copies `.agent/`). A derived project that wants the convention must replicate this file manually with its own attributions.
