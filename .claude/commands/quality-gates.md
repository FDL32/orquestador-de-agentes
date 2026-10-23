Ejecuta los Quality Gates del proyecto (los de "Criterio de cierre" en `AGENTS.md`) en este orden; la suite va la ULTIMA porque cualquier cambio posterior la invalida:

```bash
ruff check .
ruff format .
python scripts/pip_audit_project.py
python scripts/run_pytest_safe.py
```

Si `ruff format .` reformatea algo, vuelve a pasar `ruff check .` antes de la suite. Lee el resultado de cada paso con su exit code real (no tras una tuberia). Si algun paso falla, muestra el error completo, explica la causa mas probable y propone la correccion concreta. Si todos pasan, confirma con un resumen: N tests pasados / 0 failed, 0 errores ruff, formato correcto, 0 vulnerabilidades sin mitigar.
