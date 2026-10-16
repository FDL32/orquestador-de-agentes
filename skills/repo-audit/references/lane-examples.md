# Ejemplos de declaracion de lanes (Fase 0)

## Repo Python puro (el motor mismo, ambito `motor`)

```
Censo: git ls-files | wc -l -> 2.847 ficheros
LOC por lenguaje: Python 94%, Markdown 5%, otros 1%

Lanes declarados:
- lane:bus        -> bus/
- lane:scripts     -> scripts/
- lane:skills-code -> skills/*/*.py (si existen helpers)
- lane:proceso     -> prompts/*.md + skills/*/SKILL.md  (ambito=motor)
```

## Repo destino multi-lenguaje (Python + JS)

```
Censo: git ls-files | wc -l -> 15.203 ficheros
LOC por lenguaje: Python 60%, JavaScript 35%, otros 5%

Lanes declarados:
- lane:backend-py  -> backend/ (Python: vulture+ruff+pip-audit)
- lane:frontend-js -> frontend/ (JS: solo Semgrep, sin vulture/ruff;
                       degradacion declarada por R1 del nucleo)
- lane:infra       -> infra/ (Dockerfile, CI: solo Semgrep + gitleaks)
```

## Regla general

Ningun lane supera lo que un agente de Fase 2 puede leer completo con su
salida cruda sin colapsar (evitar el fallo de escala citado en el nucleo,
Seccion 0). Si un lane es demasiado grande, subdividir por sub-directorio
antes de pasar a Fase 1.
