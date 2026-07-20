Muestra el registro citable de bucles de ensemble y backend keys.

```bash
python scripts/discover_loops.py --json
```

Fuente unica: `.agent/config/agents.json::ensemble_registry`. Vista humana
generada: `docs/registry/loop_registry.md` (regenerala con
`python scripts/discover_loops.py --generate` si diverge; verifica paridad
con `python scripts/discover_loops.py --check`).

Interpreta el resultado: lista `loop_ids` (p.ej. `L700`=BUC-01, `L800`=CHA-01)
y `backend_keys` (p.ej. `BA01`=claude, `BA05`=codex, `BA10-13`=modelos nan).
Cada paso de un `loop_shape` declara `phase`, `function`
(`participant`|`consolidator`) y `backend_key`. Invariante: en bucles con
`launched_from: chat`, ningun paso puede llevar `function: consolidator` (el
consolidador es el propio chat, nivel 0, no un paso declarado).
