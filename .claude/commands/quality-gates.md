Ejecuta los Quality Gates del proyecto en este orden:

```bash
python scripts/run_pytest_safe.py --status
ruff check .agent/hooks/guard_paths.py tests --fix
ruff format .agent/hooks/guard_paths.py tests
python scripts/run_pytest_safe.py
```

Si algún paso falla, muestra el error completo, explica la causa más probable y propone la corrección concreta. Si todos pasan, confirma con un resumen: N tests pasados, 0 errores ruff, formato correcto.
