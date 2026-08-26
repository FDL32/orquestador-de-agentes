#!/usr/bin/env python3
"""Guard: un mensaje de commit NO cristaliza identidad de modelo (WOT-2026-022a).

EL PROBLEMA
-----------
El historial del motor cristalizo ~880 commits con trailers `Co-Authored-By:
<modelo literal>` (10 identidades distintas: Opus 4.5/4.7/4.8, Sonnet 4.6,
Fable 5, Haiku 4.5, Opus 5 (1M context), ...) sin fuente verificada. El costo
no es el trailer en si: es que una identidad de modelo hardcodeada en un
artefacto reutilizable (un mensaje de commit se re-lee, se compara, se cita)
se vuelve "la verdad" cuando en realidad no hay ninguna fuente runtime que
garantice que ESE modelo ejecuto ESE cambio. `prompts/orchestrator_pipeline_codeonly.md:186`
ya manda firmar con la identidad REAL y OMITIR si no se puede determinar; eso
es NORMA en prosa. Este guard es la BARRERA.

EL PREMISE-CHECK (exigido por la ficha)
---------------------------------------
"si existe fuente runtime fiable del model-id, comparar trailer vs fuente; si
no existe, no fingir validacion y degradar a warning/diagnostico."

VERIFICADO 2026-08-26 que NO existe fuente runtime fiable del modelo del
ejecutor: 0 env vars `*MODEL*`, `agents.json` `proposer_claude.model=None` y
`backend_version=None` en los 7 perfiles ensemble. Por tanto este guard NO
compara trailer-vs-fuente (no puede, no hay fuente) y NO certifica la verdad
del modelo. Su unico veredicto BLOQUEANTE es la cristalizacion MANUAL: un
trailer que lleva marca base + discriminante de modelo (variante/version/
contexto) -- es decir, una afirmacion concreta introducida a mano sin fuente.

REGLA BINARIA DEL PATRON (cerrada en el CONTRACT_AUDIT L710, Codex BA05)
-----------------------------------------------------------------------
`modelo cristalizado = display-name del trailer contiene MARCA BASE +
DISCRIMINANTE` sobre el nombre (lo que va antes del `<email>`), CON email
auto-firma tipica de modelo (`noreply@`). Marca base = proveedor/agente
(Claude, GPT, deepseek, qwen, gemma, mimo, Opus, Sonnet, Fable, Haiku, ...).
Discriminante = numeral o calificador de variante (5, 4.8, (1M context),
v4, 3.6, -v2.5, ...).

BLOQUEA (marca + discriminante + noreply@):
  - `Claude Opus 5 <noreply@anthropic.com>`
  - `Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  - `GPT-5 <noreply@openai.com>`
  - `deepseek-v4-flash <noreply@...>`

PERMITE:
  - `Claude <noreply@anthropic.com>` (marca base SIN discriminante: identifica
    proveedor/agente, no un modelo concreto -- NO es cristalizacion).
  - trailers humanos `Nombre <email@dominio.com>` (email NO noreply@).
  - ausencia de trailer `Co-Authored-By`.

NON-GOAL: NO se reescriben los ~880 commits historicos con trailers. El guard
actua SOLO sobre mensajes de commit NUEVOS (stage commit-msg).

Before: argv[1] es la ruta al fichero de mensaje de commit que aporta git
    (`.git/COMMIT_EDITMSG`); se lee como UTF-8.
During: filtra comentarios (`#` scissors de git) y localiza lineas
    `Co-Authored-By: <identidad> <email>`. Para cada una, aplica la regla
    binaria marca+discriminante. Sin escritura.
After: exit 1 con diagnostico si hay cristalizacion de modelo; exit 0 si el
    mensaje esta limpio o solo lleva proveedor/co-autoria humana. Fallo de
    lectura/uso degrades a exit 0 (un guard roto no debe bloquear todo commit:
    el mismo criterio fail-open que check_commit_message_encoding).
"""

from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path


# Marca base: proveedor/agente o lineage de modelo. Case-insensitive porque los
# trailers variaron en forma real (medido: "Claude", "GPT", "deepseek", "mimo").
_BASE_MARKS = (
    "claude",
    "gpt",
    "deepseek",
    "qwen",
    "gemma",
    "mimo",
    "opus",
    "sonnet",
    "haiku",
    "fable",
    "llama",
    "glm",
)
_BASE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _BASE_MARKS) + r")\b",
    re.IGNORECASE,
)

# Discriminante: numeral o calificador de variante/version/contexto.
# - `4.8`, `5`, `3.6`, `2.5` (numeros)
# - `(1M context)`, `(1M)` (contexto)
# - `v4`, `-v2.5`, `v1M` (version)
# Las variantes parentetizadas van SIN `\b` exterior (Codex L810): `\b` no tiene
# frontera de palabra antes de `(` ni despues de `)`, asi que `Claude Opus
# (1M context)` quedaba sin discriminante y pasaba en verde -- falso negativo
# contra la regla cerrada del contrato.
_DISCRIMINATOR_RE = re.compile(
    r"(?:\b\d+\.?\d*\b|\bv\d+(?:\.\d+)?\b|\(\d+[A-Za-z]?\s*(?:context)?\)|\([^)]*\d[^)]*\))",
    re.IGNORECASE,
)

# Email auto-firma tipica de modelo (noreply@<proveedor>): lo que distingue una
# firma de agente/proveedor de una co-autoria humana real.
_NOREPLY_RE = re.compile(r"<\s*noreply@[^>]+>", re.IGNORECASE)

# Linea de trailer de co-autoria (git trailer).
_CO_AUTHOR_RE = re.compile(
    r"^\s*Co-Authored-By\s*:\s*(?P<ident>[^<]+)(?P<email><[^>]+>)?",
    re.IGNORECASE,
)


def strip_comments(message: str) -> str:
    """Drop git's comment lines (scissors/template) so boilerplate never fires."""
    return "\n".join(
        line for line in message.splitlines() if not line.lstrip().startswith("#")
    )


def crystallization_issues(message: str) -> list[str]:
    """Trailers `Co-Authored-By` que cristalizan identidad de MODELO concreto.

    Before: `message` es el mensaje de commit sin comentarios.
    During: recorre cada linea, identifica trailers de co-autoria, y aplica la
        regla binaria marca base + discriminante + email noreply@. Sin I/O.
    After: lista de diagnosticos (vacia = sin cristalizacion de modelo).
    """
    issues: list[str] = []
    for line in message.splitlines():
        m = _CO_AUTHOR_RE.match(line)
        if not m:
            continue
        ident = m.group("ident").strip()
        email = (m.group("email") or "").strip()
        has_noreply = bool(_NOREPLY_RE.search(email))
        has_base = bool(_BASE_RE.search(ident))
        has_disc = bool(_DISCRIMINATOR_RE.search(ident))
        if has_base and has_noreply and has_disc:
            issues.append(
                f"trailer Co-Authored-By cristaliza identidad de MODELO: {ident!r} "
                f"{email} (marca base + discriminante + auto-firma noreply@). "
                "Sin fuente runtime fiable del modelo, una identidad concreta es "
                "cristalizacion no verificable. Firmar solo con el proveedor "
                "(p.ej. 'Claude <noreply@...>') o con identidad humana, o "
                "OMITIR el trailer (orchestrator_pipeline_codeonly.md:186)."
            )
    return issues


def _force_utf8_stderr() -> None:
    """Make stderr UTF-8-safe on the Windows console codepage."""
    with contextlib.suppress(AttributeError, OSError, ValueError):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """CLI: git pasa la ruta del mensaje de commit en argv[1]."""
    _force_utf8_stderr()
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(
            "[model-id-crystallization] sin ruta de mensaje; nada que revisar",
            file=sys.stderr,
        )
        return 0

    path = Path(args[0])
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        # Fail OPEN en error del GUARD (no del mensaje): un guard roto no puede
        # bloquear la entrega. Mismo criterio que check_commit_message_encoding.
        print(
            f"[model-id-crystallization] no se pudo leer {path}: {e} (no bloquea)",
            file=sys.stderr,
        )
        return 0

    message = strip_comments(raw)
    issues = crystallization_issues(message)
    if issues:
        print(
            "[model-id-crystallization] ERROR: el mensaje de commit cristaliza identidad de modelo:",
            file=sys.stderr,
        )
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        print(
            "  Remedio: firmar con el proveedor (sin version) o con identidad humana,"
            "o quitar el trailer. No existe fuente runtime que valide un modelo concreto.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
