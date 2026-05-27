# Security guidance for orquestador_de_agentes

- Never read or write `privada/` or any `.env` file. `guard_paths` already enforces this.
- Do not log ticket IDs together with credentials or tokens at any level.
- `events.jsonl` and `observations.jsonl` are append-only; never truncate or overwrite them.
- `uv add` is the only approved way to add dependencies; never call `pip install` directly.
