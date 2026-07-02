r"""WOT-2026-016d - Barrera de regresion del callback de ruta-username (gap + anti-sobre-redaccion).

Doble proposito:
 1. EVIDENCIA DEL GAP (regex v1): prueba, reproducible y SIN PII, que el regex de la 1a pasada
    (`[a-z]:[/\\]users[/\\]<token>`, copiado de bus/redact.py) NO cubre 3 formas del username
    -> por eso la Rev2 (G3) RECHAZO 016d (residuo en runtime/project_root.py,
    scripts/claude_memory_mirror.py, prompts/orchestrator_launch_builder.md; + 6o fixture
    tests/test_classify_publication.py).
 2. BARRERA DEL v2 (la 2a pasada DEBE cumplir): las 3 formas -> REDACTED, PERO el alias GitHub
    publico -> INTACTO. Anti-sobre-redaccion: el username-OS (3 chars) es SUBSTRING del handle
    `FDL32` (128408907+FDL32@users.noreply.github.com), que es PUBLICO y DEBE PRESERVARSE; un patron
    sin anclar al contexto `Users<sep>` seria una catastrofe de sobre-redaccion en toda la historia.

DOS CAPAS distintas (no confundir):
 - REGEX (este test): redacta el username cuando va tras `Users<sep>`. El alias FDL32 NO matchea
   porque ahi `users` va seguido de `.noreply`, no de un separador + username -> queda intacto.
 - ALLOWLIST DE PATHS (en el callback real, NO aqui): los fixtures `name`/`x` (`C:\Users\name`) SI
   matchean la regex, pero se preservan porque su ARCHIVO esta en la allowlist (RD2/D4), no porque
   la regex los ignore. Por eso NO van como negativos-de-regex en este test.

Se usa el username GENERICO 'usr' en los casos POSITIVOS para no re-introducir PII.

Ejecutar:  .venv/Scripts/python.exe .agent/collaboration/CALLBACK_GAP_016d_test_forms.py
Con la regex v1 (abajo): los POSITIVOS single-`\`/`/` dan REDACTED; las 3 formas del gap dan MISSED
  -> demuestra el gap. Los NEGATIVOS quedan intactos (v1 ya los respeta por estar anclados a Users).
El v2 (regex ampliada, a escribir en la sesion correctiva) DEBE hacer que los 5 POSITIVOS den
  REDACTED y los NEGATIVOS sigan intactos. Pega aqui la regex v2 y re-corre: exit 0 sii todo cuadra.
"""

import re
import sys


# --- Regex v1 (1a pasada). CONSERVADA como evidencia del gap (RECHAZO Rev2/G3). ---
V1 = re.compile(rb"(?i)([a-z]:[/\\]users[/\\])([a-zA-Z0-9_-]+)")


def redact_v1(data: bytes) -> bytes:
    return V1.sub(rb"\1***REDACTED***", data)


# --- Regex v2 (2a pasada, CORRECTIVA). FORMA del patron bajo prueba: ancla a `Users<seps>` +
# username HARDCODED, sin consumir el terminador -> preserva prefijo y lo-que-sigue; cubre las 3
# formas del gap (`\\`, no-separador, dash-slug) SIN sobre-redactar el alias publico FDL32 (va tras
# `+`, no tras `Users<sep>`). `[/\\+-]*` = 0 seps (no-sep slug) | 1 (`\`/`/`/`-`) | 2 (`\\`).
# El TOKEN se parametriza: el test usa el generico 'usr' (fixtures PII-free); el callback real
# instancia el MISMO shape con 'fdl'. Lo que valida el gate es la FORMA, no el literal. ---
_V2_TOKEN = rb"usr"  # username generico de los fixtures POSITIVE (sin PII); el callback real usa 'fdl'.
V2 = re.compile(rb"(?i)(users[/\\+-]*)(" + _V2_TOKEN + rb")")


def redact_v2(data: bytes) -> bytes:
    return V2.sub(rb"\1***REDACTED***", data)


# POSITIVOS: el username DEBE redactarse. 'usr' generico (sin PII). Esperado en v2: REDACTED todos.
POSITIVE = {
    "single-backslash": rb"C:\Users\usr\proj",
    "forward-slash": rb"C:/Users/usr/proj",
    "DOUBLE-backslash": rb"C:\\Users\\usr\\proj",  # literal Python '\\' -> v1 MISSED
    "no-separator-slug": rb"UsersusrProyectos",  # separadores eliminados -> v1 MISSED
    "dash-slug": rb"c--Users-usr-Proyectos",  # slug con guiones -> v1 MISSED
}

# NEGATIVOS-DE-REGEX: la regex NO los debe tocar (no van tras `Users<sep>` como username).
# Barrera anti-sobre-redaccion del alias publico. (Los fixtures name/x NO van aqui: los protege la
# allowlist de PATHS del callback real, no la regex; ver docstring "DOS CAPAS".)
NEGATIVE = {
    "github-alias-PUBLIC": rb"128408907+FDL32@users.noreply.github.com",  # publico, NO PII
    "unrelated-users-word": rb"the users guide at docs/users/readme",  # 'users' sin ser ruta-username
}


def run(redact):
    """Devuelve (all_positive_redacted, all_negative_intact)."""
    pos_ok = True
    neg_ok = True
    print("POSITIVOS (deben quedar REDACTED con v2):")
    for name, data in POSITIVE.items():
        out = redact(data)
        red = out != data
        if not red:
            pos_ok = False
        print(
            "  [" + ("REDACTED" if red else "MISSED  ") + "] " + name + ": " + repr(out)
        )
    print("NEGATIVOS (deben quedar INTACTOS - anti-sobre-redaccion):")
    for name, data in NEGATIVE.items():
        out = redact(data)
        intact = out == data
        if not intact:
            neg_ok = False
        print(
            "  ["
            + ("INTACT  " if intact else "OVER-RED")
            + "] "
            + name
            + ": "
            + repr(out)
        )
    return pos_ok, neg_ok


if __name__ == "__main__":
    # DOS MODOS (2a auditoria: el exit 0 por-defecto NO significa "gate verde completo"):
    #  (default)  modo EVIDENCIA: reporta; exit 0 sii los NEGATIVOS estan intactos (barrera base).
    #             Con la regex v1, 3 positivos dan MISSED a proposito: eso ES el gap documentado.
    #  --gate     modo GATE del v2: exit 0 SOLO si POSITIVOS 5/5 REDACTED **Y** NEGATIVOS INTACT.
    #             Con v1 este modo DEBE fallar (exit 1). La sesion correctiva pega su regex v2 en
    #             redact_v1 (o importa la suya) y NO aplica el callback hasta que `--gate` de 0.
    # --gate corre la v2 CORRECTIVA (debe dar VERDE); default corre la v1 (evidencia del gap).
    _gate = "--gate" in sys.argv[1:]
    _redact = redact_v2 if _gate else redact_v1
    pos_ok, neg_ok = run(_redact)
    if _gate:
        verdict = pos_ok and neg_ok
        print(
            "GATE v2: "
            + ("VERDE (5/5 REDACTED + negativos INTACT)" if verdict else "ROJO")
        )
        sys.exit(0 if verdict else 1)
    sys.exit(0 if neg_ok else 1)
