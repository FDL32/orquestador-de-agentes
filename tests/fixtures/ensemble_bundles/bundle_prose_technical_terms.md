DIAGNOSTICO A ADJUDICAR (razona; no asumas mi hipotesis correcta).
Entorno: Windows, cwd=repo_motor.

<!-- FIXTURE ANTI-FALSO-POSITIVO (WOT-2026-027n), DoD (c).
     Copiado de un bundle REAL de .agent/runtime/tmp/ (codex_ensemble_run_hang.md,
     2026-07-21). Se VERSIONA aqui a proposito: .agent/runtime/tmp/ esta
     GITIGNORED (.gitignore:16) y un fixture sobre ficheros efimeros se evapora
     en la primera purga -> test flaky por construccion.
     ESTE BUNDLE DEBE **PASAR** el gate de contenido: menciona los terminos
     sensibles en PROSA TECNICA, no como asignacion con valor de alta entropia.
     Un gate por substring lo bloquearia, y con el bloquearia el trabajo real
     del repo. -->

SINTOMA MEDIDO (2026-07-21, ~5 veces, incluido tras reinicio del sistema):
- `python scripts/ensemble_dispatch.py smoke` -> PASA (6/6 backends alive).
- `run --pipeline review_adversarial --task-type code-review --payload-file <4KB>`
  -> FALLA SIEMPRE con "RuntimeError: backend CLI sin respuesta tras 120s".

HIPOTESIS DESCARTADAS:
- No es la api_key: la misma variable de entorno sirve al smoke, que pasa.
- No es el token de auth caducado: el 401 se veria como cuerpo, no como hang.
- No es una clave mal resuelta: privacy_preflight corre ANTES de tocar red y
  habria lanzado DispatchBlockedError, no un timeout.
- Las claves de estilo `sk-` de OpenAI no intervienen: este canal es nan_api.

PREGUNTA: por que el hang aparece solo en la ruta `run` y no en `smoke`?
